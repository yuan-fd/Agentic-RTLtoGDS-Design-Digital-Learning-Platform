"""Platform-managed Codex provider for RTLScout's native Python ReAct agent.

This module adapts only RTLScout's public ``LLMClient.chat_completion`` seam.
It does not implement an RTL candidate loop, execute EDA, or choose the best
design.  Those responsibilities remain in the pinned upstream ``RTLAgent``.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence


EXECUTED_MODEL = "gpt-5.6-terra"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _strict_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Convert an upstream tool schema to Codex strict structured output.

    Optional object properties become required nullable properties because the
    Codex output-schema dialect requires every declared property in
    ``required``.  Null optionals are removed before RTLScout receives the
    tool arguments.
    """

    result = dict(schema)
    if result.get("type") == "object":
        properties = result.get("properties") or {}
        originally_required = set(result.get("required") or ())
        strict_properties: dict[str, Any] = {}
        for name, child in properties.items():
            converted = _strict_schema(child)
            if name not in originally_required:
                converted = {"anyOf": [converted, {"type": "null"}]}
            strict_properties[name] = converted
        result["properties"] = strict_properties
        result["required"] = list(properties)
        result["additionalProperties"] = False
    if result.get("type") == "array" and isinstance(result.get("items"), Mapping):
        result["items"] = _strict_schema(result["items"])
    for keyword in ("anyOf", "oneOf", "allOf"):
        if isinstance(result.get(keyword), list):
            result[keyword] = [_strict_schema(item) for item in result[keyword]]
    return result


def _compact_messages(messages: Sequence[Mapping[str, Any]]) -> str:
    return json.dumps(list(messages), ensure_ascii=False, separators=(",", ":"))


def _tool_response_schema(tools: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    names: list[str] = []
    argument_properties: dict[str, Any] = {}
    for tool in tools:
        function = tool.get("function") or {}
        name = function.get("name")
        parameters = function.get("parameters")
        if not isinstance(name, str) or not isinstance(parameters, Mapping):
            raise ValueError("RTLScout supplied a malformed tool definition")
        names.append(name)
        for argument_name, argument_schema in (parameters.get("properties") or {}).items():
            converted = _strict_schema(argument_schema)
            nullable = {"anyOf": [converted, {"type": "null"}]}
            previous = argument_properties.get(argument_name)
            # Shared names such as ``filename`` carry tool-specific prose but
            # the same primitive shape at this pinned commit.  Keep the first
            # schema; the selected tool's own required set is checked later.
            if previous is None:
                argument_properties[argument_name] = nullable
    if not names:
        raise ValueError("RTLScout native agent supplied no tools")
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["content", "tool_call"],
        "properties": {
            "content": {"type": "string", "maxLength": 12000},
            # A flat envelope avoids ambiguous anyOf branch selection while
            # retaining a closed typed result.  Only the fields declared by
            # the selected upstream tool survive the projection below.
            "tool_call": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "arguments"],
                "properties": {
                    "name": {"type": "string", "enum": names},
                    "arguments": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": list(argument_properties),
                        "properties": argument_properties,
                    },
                },
            },
        },
    }


def _drop_null_optionals(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _drop_null_optionals(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_drop_null_optionals(item) for item in value]
    return value


class ManagedCodexRTLScoutClient:
    """RTLScout ``LLMClient``-compatible facade backed by managed Codex."""

    def __init__(self, *, model: str, executable: str | Path,
                 trace_path: str | Path, timeout_seconds: int = 600):
        self.model = model
        self.executable = Path(executable).expanduser().absolute()
        self.trace_path = Path(trace_path).resolve()
        self.timeout_seconds = timeout_seconds
        self.calls: list[dict[str, Any]] = []
        if not self.executable.is_file() or not os.access(self.executable, os.X_OK):
            raise FileNotFoundError("platform-managed Codex executable is unavailable")

    def chat_completion(self, messages: list[dict[str, Any]],
                        tools: list[dict[str, Any]] | None,
                        tool_choice: str | None = "auto") -> Any:
        # Import from the pinned checkout only after the native driver has put
        # it on sys.path.  Returning upstream's own dataclasses keeps this seam
        # protocol-only and avoids a second agent implementation.
        from core.llm_client import ChatResponse, TokenUsage, ToolCall

        compact = _compact_messages(messages)
        if tools:
            schema = _tool_response_schema(tools)
            tool_catalog = json.dumps(tools, ensure_ascii=False, separators=(",", ":"))
            instruction = (
                "You are the language-policy component inside the pinned RTLScout Python ReAct agent. "
                "Return exactly one JSON object matching the supplied schema, including exactly one of "
                "RTLScout's listed tool calls. Do not execute commands or EDA yourself and do not claim "
                "that a candidate passed; RTLScout executes the selected tool and provides measured feedback. "
                "Use only paths inside its workspace. Follow each tool description exactly: in particular, "
                "use create_file (not edit_file) when the design file does not exist. "
                f"RTLScout tool catalog: {tool_catalog}\n"
                "The complete RTLScout conversation follows:\n"
            )
            result_kind = "tool_call"
        else:
            schema = {
                "type": "object",
                "additionalProperties": False,
                "required": ["content"],
                "properties": {"content": {"type": "string", "maxLength": 12000}},
            }
            instruction = (
                "Write the concise end-of-run summary requested by the pinned RTLScout agent. "
                "Return exactly one JSON object matching the supplied schema. Do not invent measurements; "
                "use only facts in the conversation that follows:\n"
            )
            result_kind = "summary"
        prompt = instruction + compact

        launcher_dir = self.executable.parent
        environment = {
            key: os.environ[key]
            for key in ("HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "TZ", "CODEX_HOME")
            if key in os.environ
        }
        environment["PATH"] = f"{launcher_dir}{os.pathsep}{os.environ.get('PATH', os.defpath)}"
        with tempfile.TemporaryDirectory(prefix="rtlscout-managed-provider-") as raw:
            temp_root = Path(raw)
            schema_path = temp_root / "schema.json"
            output_path = temp_root / "output.json"
            _write_json(schema_path, schema)
            completed = subprocess.run(
                [
                    str(self.executable), "exec", "--ephemeral", "--ignore-rules",
                    "--skip-git-repo-check", "--sandbox", "read-only", "--model",
                    EXECUTED_MODEL, "--output-schema", str(schema_path),
                    "--output-last-message", str(output_path), "--color", "never", "-",
                ],
                input=prompt,
                cwd=temp_root,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_seconds,
                check=False,
            )
            if completed.returncode != 0 or not output_path.is_file():
                detail = "\n".join((completed.stderr or completed.stdout).splitlines()[-16:])
                raise RuntimeError(detail or "managed Codex provider returned no structured result")
            value = json.loads(output_path.read_text(encoding="utf-8"))
        if not isinstance(value, Mapping):
            raise ValueError("managed Codex provider returned a non-object")

        record: dict[str, Any] = {
            "call_index": len(self.calls),
            "requested_model": self.model,
            "executed_model": EXECUTED_MODEL,
            "model_substitution": self.model != EXECUTED_MODEL,
            "prompt_sha256": _digest(prompt),
            "schema_sha256": _digest(json.dumps(schema, sort_keys=True)),
            "result_sha256": _digest(json.dumps(value, sort_keys=True)),
            "result_kind": result_kind,
        }
        if tools:
            action = value.get("tool_call")
            if not isinstance(action, Mapping):
                raise ValueError("managed Codex response lacks a typed RTLScout tool call")
            name = action.get("name")
            definitions = {
                (item.get("function") or {}).get("name"): item.get("function") or {}
                for item in tools
            }
            if name not in definitions:
                raise ValueError(f"managed Codex selected an unknown RTLScout tool: {name!r}")
            raw_arguments = action.get("arguments")
            if not isinstance(raw_arguments, Mapping):
                raise ValueError("managed Codex tool arguments are not an object")
            parameters = definitions[name].get("parameters") or {}
            selected_properties = set((parameters.get("properties") or {}).keys())
            arguments = _drop_null_optionals({
                key: value for key, value in raw_arguments.items()
                if key in selected_properties
            })
            missing = set(parameters.get("required") or ()) - set(arguments)
            if missing:
                raise ValueError(
                    f"managed Codex omitted required {name} arguments: {sorted(missing)}"
                )
            content = value.get("content")
            if not isinstance(content, str):
                raise ValueError("managed Codex response content is not a string")
            record.update({"tool_name": name, "typed_arguments": arguments, "content": content})
            response = ChatResponse(
                content=content,
                tool_calls=[ToolCall(
                    id=f"call_{uuid.uuid4().hex}",
                    name=str(name),
                    arguments=json.dumps(arguments, ensure_ascii=False),
                )],
                usage=TokenUsage(),
            )
        else:
            content = value.get("content")
            if not isinstance(content, str):
                raise ValueError("managed Codex summary lacks content")
            record["content"] = content
            response = ChatResponse(content=content, tool_calls=[], usage=TokenUsage())

        self.calls.append(record)
        _write_json(self.trace_path, {
            "schema_version": 1,
            "provider": "platform-managed-codex-cli",
            "executed_model": EXECUTED_MODEL,
            "credential_source": "platform-managed Codex authentication; no API key in TaskSpec",
            "native_agent_owner": "huawei-csl/rtlscout core.agent.RTLAgent",
            "calls": self.calls,
        })
        return response
