"""OpenAI-compatible facade backed by the platform-managed Codex CLI.

A2-ORFO imports :class:`openai.OpenAI` directly in several upstream modules.
The platform installs this module as ``sys.modules['openai']`` before loading
the pinned source.  It implements only the chat-completions surface exercised
by that commit.  It never accepts a browser/user API key and it records every
model substitution and typed result in an attempt-local trace.
"""
from __future__ import annotations

import hashlib
import importlib.machinery
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import types
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence


EXECUTED_MODEL = "gpt-5.6-terra"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def _strict_schema(value: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize an upstream function schema for Codex structured output.

    The upstream OpenAI-compatible endpoint accepted omitted
    ``additionalProperties`` and optional object fields.  Codex structured
    output requires closed objects and all declared properties in ``required``.
    This is a provider-protocol adaptation only; the value ranges/enums and
    A2-ORFO's subsequent interpretation remain unchanged.
    """
    result = dict(value)
    if result.get("type") == "object":
        properties = result.get("properties") or {}
        result["properties"] = {name: _strict_schema(item) for name, item in properties.items()}
        result["additionalProperties"] = False
        result["required"] = list(properties)
    if result.get("type") == "array" and isinstance(result.get("items"), Mapping):
        result["items"] = _strict_schema(result["items"])
    for combinator in ("anyOf", "oneOf", "allOf"):
        if isinstance(result.get(combinator), list):
            result[combinator] = [_strict_schema(item) for item in result[combinator]]
    return result


def _message_text(messages: Sequence[Any]) -> str:
    rows = []
    for message in messages:
        if isinstance(message, Mapping):
            rows.append({"role": str(message.get("role", "")), "content": str(message.get("content", ""))})
        else:
            rows.append({"role": "unknown", "content": str(message)})
    return json.dumps(rows, ensure_ascii=False, sort_keys=True)


class ManagedCodexProvider:
    def __init__(self, *, executable: str | Path, trace_path: str | Path,
                 timeout_seconds: int = 240):
        self.executable = Path(executable).expanduser().absolute()
        self.trace_path = Path(trace_path).resolve()
        self.timeout_seconds = timeout_seconds
        self.calls: list[dict[str, Any]] = []
        if not self.executable.is_file() or not os.access(self.executable.resolve(), os.X_OK):
            raise FileNotFoundError("platform-managed Codex executable is unavailable")

    def _selected_tool(self, prompt: str, tools: Sequence[Mapping[str, Any]],
                       tool_choice: Any) -> Mapping[str, Any]:
        if isinstance(tool_choice, Mapping):
            requested = ((tool_choice.get("function") or {}).get("name"))
            for tool in tools:
                if (tool.get("function") or {}).get("name") == requested:
                    return tool
            raise ValueError(f"A2-ORFO requested an unknown tool: {requested}")
        # The complete upstream prompt mentions every stage in explanatory
        # prose.  Dispatch only on A2-ORFO's explicit current-stage marker;
        # generic substring matching can silently route MODEL to SELECTION.
        match = re.search(r"(?:CURRENT STAGE:|\*\*STAGES:)\s*(INSPECTION|MODEL|SELECTION)",
                          prompt.upper())
        if match:
            expected = {
                "INSPECTION": "configure_inspection", "MODEL": "configure_model",
                "SELECTION": "configure_selection",
            }[match.group(1)]
            for tool in tools:
                if (tool.get("function") or {}).get("name") == expected:
                    return tool
            raise ValueError(f"A2-ORFO current stage {match.group(1)} lacks its typed tool")
        if len(tools) == 1:
            return tools[0]
        raise ValueError("cannot determine the typed A2-ORFO tool for this upstream prompt")

    def complete(self, *, model: str, messages: Sequence[Any],
                 tools: Sequence[Mapping[str, Any]] | None = None,
                 tool_choice: Any = None, temperature: Any = None,
                 max_tokens: Any = None, **_: Any) -> Any:
        compact_messages = _message_text(messages)
        selected = self._selected_tool(compact_messages, tools, tool_choice) if tools else None
        if selected:
            function = selected["function"]
            schema = _strict_schema(function["parameters"])
            expected_kind = "tool_call"
            instruction = (
                "Act only as the bounded language-policy component requested by the pinned "
                "A2-ORFO workflow. Return exactly one JSON object matching the supplied schema. "
                "Do not run commands, edit files, invent measurements, or claim EDA success. "
                f"The JSON object is the arguments for function {function['name']}.\n\n"
            )
        else:
            schema = {
                "type": "object", "additionalProperties": False,
                "required": ["content"],
                "properties": {"content": {"type": "string", "maxLength": 12000}},
            }
            expected_kind = "text"
            instruction = (
                "Act only as the bounded reviewer/prompt-policy component requested by the "
                "pinned A2-ORFO workflow. Return exactly one JSON object matching the supplied "
                "schema. Do not run commands, edit files, invent measurements, or claim EDA success.\n\n"
            )
        prompt = instruction + compact_messages
        launcher_dir = self.executable.parent
        environment = {
            key: os.environ[key]
            for key in ("HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "TZ", "CODEX_HOME")
            if key in os.environ
        }
        inherited_path = os.environ.get("PATH", os.defpath)
        environment["PATH"] = f"{launcher_dir}{os.pathsep}{inherited_path}"
        with tempfile.TemporaryDirectory(prefix="a2-orfo-managed-provider-") as raw:
            root = Path(raw)
            schema_path, output_path = root / "schema.json", root / "output.json"
            _write(schema_path, schema)
            command = [str(self.executable), "exec", "--ephemeral", "--ignore-rules",
                       "--skip-git-repo-check", "--sandbox", "read-only", "--model",
                       EXECUTED_MODEL, "--output-schema", str(schema_path),
                       "--output-last-message", str(output_path), "--color", "never", "-"]
            completed = subprocess.run(
                command, input=prompt, cwd=root, env=environment, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=self.timeout_seconds, check=False,
            )
            # Capacity errors are provider-level and transient. Retry once with
            # the identical pinned model and prompt; all other failures remain
            # fail-closed and are surfaced immediately.
            if completed.returncode != 0 and "at capacity" in (completed.stderr or "").lower():
                time.sleep(2)
                completed = subprocess.run(
                    command, input=prompt, cwd=root, env=environment, text=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    timeout=self.timeout_seconds, check=False,
                )
            if completed.returncode != 0 or not output_path.is_file():
                detail = "\n".join((completed.stderr or completed.stdout).splitlines()[-12:])
                raise RuntimeError(detail or "managed Codex provider returned no result")
            value = json.loads(output_path.read_text(encoding="utf-8"))
        if not isinstance(value, Mapping):
            raise ValueError("managed Codex provider returned a non-object")
        record: dict[str, Any] = {
            "call_index": len(self.calls), "requested_model": model,
            "executed_model": EXECUTED_MODEL, "model_substitution": model != EXECUTED_MODEL,
            "prompt_sha256": _digest(prompt), "schema_sha256": _digest(json.dumps(schema, sort_keys=True)),
            "result_sha256": _digest(json.dumps(value, sort_keys=True)), "result_kind": expected_kind,
            "temperature_requested": temperature, "max_tokens_requested": max_tokens,
        }
        if selected:
            record["function_name"] = selected["function"]["name"]
            record["typed_arguments"] = dict(value)
        else:
            content = value.get("content")
            if not isinstance(content, str):
                raise ValueError("managed Codex text response lacks content")
            record["content_length"] = len(content)
        self.calls.append(record)
        _write(self.trace_path, {
            "schema_version": 1, "provider": "platform-managed-codex-cli",
            "executed_model": EXECUTED_MODEL, "calls": self.calls,
            "credential_source": "platform-managed Codex authentication; no API key in TaskSpec",
        })
        if selected:
            function = types.SimpleNamespace(
                name=selected["function"]["name"],
                arguments=json.dumps(value, ensure_ascii=False),
            )
            tool_call = types.SimpleNamespace(id=f"call_{uuid.uuid4().hex}", function=function)
            message = types.SimpleNamespace(content=None, tool_calls=[tool_call])
        else:
            message = types.SimpleNamespace(content=value["content"], tool_calls=[])
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])


def install_openai_shim(provider: ManagedCodexProvider) -> None:
    """Install the narrow facade before importing any upstream A2 module."""
    class Completions:
        def create(self, **kwargs: Any) -> Any:
            return provider.complete(**kwargs)

    class OpenAI:
        def __init__(self, *_: Any, **__: Any):
            self.chat = types.SimpleNamespace(completions=Completions())

    shim = types.ModuleType("openai")
    # ``transformers`` probes optional dependencies with ``find_spec`` while
    # the embedding model loads; a programmatically installed module needs a
    # non-null spec for that standards-compliant probe.
    shim.__spec__ = importlib.machinery.ModuleSpec("openai", loader=None)
    shim.OpenAI = OpenAI
    sys.modules["openai"] = shim
