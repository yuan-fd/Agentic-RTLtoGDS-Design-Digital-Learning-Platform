"""Managed Codex-CLI structured provider for L1 GoalDraft parsing.

The provider is a replaceable language front-end: it returns the same typed
``GoalDraft``-shaped JSON as the deterministic tutorial parser.  GoalFinalizer
and Policy keep all authority over the resulting Goal.  There is deliberately
no fallback to a deterministic parser: a failed or unverifiable model output
raises so the operator sees the failure instead of silently changing
behaviour.  This module has no tool, shell, or Runtime execution port.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping

from openroad_platform_contracts.l1_goal_draft import ClarificationField, GoalIntent

ALLOWED_L1_MODELS = frozenset({"gpt-5.6-terra"})
_SOURCE_VALUES = ("user", "operator_profile", "safe_default", "derived")
_INTENT_VALUES = tuple(item.value for item in GoalIntent)
_FIELD_VALUES = tuple(item.value for item in ClarificationField)


def _draft_schema() -> dict[str, Any]:
    """Strict JSON Schema for the one bounded GoalDraft-shaped response."""
    identifier = {"type": "string", "pattern": "^[A-Za-z0-9_-]+$"}
    field_enum = {"type": "string", "enum": list(_FIELD_VALUES)}
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "request_text": {"type": "string", "minLength": 1, "maxLength": 8000},
            "schema_version": {"const": 1},
            "intent": {"type": "string", "enum": list(_INTENT_VALUES)},
            "questions": {
                "type": "array",
                "items": {
                    "type": "object", "additionalProperties": False,
                    "properties": {
                        "question_id": identifier,
                        "field": field_enum,
                        "prompt": {"type": "string", "minLength": 1, "maxLength": 2000},
                        "blocking": {"type": "boolean"},
                        "schema_version": {"const": 1},
                    },
                    "required": ["question_id", "field", "prompt", "blocking", "schema_version"],
                },
            },
            "answers": {
                "type": "array",
                "items": {
                    "type": "object", "additionalProperties": False,
                    "properties": {
                        "question_id": identifier,
                        "field": field_enum,
                        "value": {"type": "string", "minLength": 1, "maxLength": 4000},
                        "schema_version": {"const": 1},
                    },
                    "required": ["question_id", "field", "value", "schema_version"],
                },
            },
            "interpretation": {
                "type": "object",
                "additionalProperties": {"type": "string", "minLength": 1, "maxLength": 4000},
            },
            "field_sources": {
                "type": "object",
                "additionalProperties": {"type": "string", "enum": list(_SOURCE_VALUES)},
            },
        },
        "required": ["request_text", "schema_version", "intent", "questions",
                     "answers", "interpretation", "field_sources"],
    }


class CodexGoalDraftProvider:
    """Ephemeral structured-output provider backed by the managed Codex CLI."""

    provider_id = "codex-cli-l1-goal-v1"

    def __init__(self, *, model: str = "gpt-5.6-terra", timeout_seconds: int = 180,
                 executable: str | Path | None = None):
        if model not in ALLOWED_L1_MODELS:
            raise ValueError(f"L1 model is not allowlisted: {model}")
        if not 1 <= timeout_seconds <= 600:
            raise ValueError("Codex timeout must be between 1 and 600 seconds")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.executable = str(executable or shutil.which("codex") or "")
        if not self.executable:
            raise FileNotFoundError("codex CLI is unavailable for the L1 goal provider")

    def complete(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(request, Mapping) or request.get("kind") not in {"goal_draft", "goal_draft_revision"}:
            raise ValueError("goal provider received an unsupported request kind")
        prompt = self._prompt(request)
        with tempfile.TemporaryDirectory(prefix="openroad-l1-goal-") as raw:
            root = Path(raw)
            schema_path = root / "schema.json"
            output_path = root / "proposal.json"
            schema_path.write_text(json.dumps(_draft_schema()), encoding="utf-8")
            env = {key: os.environ[key] for key in (
                "HOME", "USER", "LOGNAME", "PATH", "LANG", "LC_ALL", "TZ", "CODEX_HOME"
            ) if key in os.environ}
            returncode = self._run_codex(prompt, schema_path, output_path, env)
            if returncode != 0 or not output_path.is_file():
                raise RuntimeError("Codex L1 goal provider returned no structured proposal")
            try:
                value = json.loads(output_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise RuntimeError("Codex L1 goal provider returned invalid JSON") from exc
        if not isinstance(value, Mapping):
            raise RuntimeError("Codex L1 goal provider must return a JSON object")
        return value

    def _run_codex(self, prompt: str, schema_path: Path, output_path: Path,
                   env: Mapping[str, str]) -> int:
        result = subprocess.run(
            [self.executable, "exec", "--ephemeral", "--ignore-rules",
             "--skip-git-repo-check", "--sandbox", "read-only", "--model", self.model,
             "--output-schema", str(schema_path), "--output-last-message", str(output_path),
             "--color", "never", "-"],
            input=prompt, cwd=str(output_path.parent), env=dict(env), text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=self.timeout_seconds, check=False,
        )
        return result.returncode

    def _prompt(self, request: Mapping[str, Any]) -> str:
        """One bounded instruction; the model may return typed JSON only."""
        if request.get("kind") == "goal_draft_revision":
            context = (
                "REVISION of an existing draft. Keep request_text, interpretation and "
                "field_sources unchanged. Keep every existing question with the same "
                "question_id, field and blocking value. Record the supplied answers by "
                "question_id and add no answers for questions that were not asked."
            )
        else:
            context = "INITIAL parse of one natural-language EDA goal."
        instruction = (
            "You are a constrained EDA goal interpreter. Return only the JSON object "
            "described by the schema. Do not invent a design, toolchain or budget: "
            "when the request omits a policy-relevant fact, ask one concise blocking "
            "clarification question (question_id, field, prompt, blocking=true). "
            "intent must be one of diagnose/execute/optimize/compare/explain. "
            "request_text must equal the supplied user request verbatim. "
            "Every key in interpretation must have the same key in field_sources with "
            "one of user/operator_profile/safe_default/derived. Never emit commands, "
            "paths, credentials, tool names, or RTL source: this is a typed language "
            "draft only.\n\n"
            f"{context}\n"
            f"USER_REQUEST={json.dumps(request.get('request_text'), ensure_ascii=False)}\n"
            f"PRIOR_DRAFT={json.dumps(request.get('prior_draft'), ensure_ascii=False)}\n"
            f"ANSWERS={json.dumps(request.get('answers'), ensure_ascii=False)}\n"
        )
        return instruction
