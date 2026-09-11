"""Managed Codex-CLI structured provider for L1 GoalDraft parsing.

The provider is a replaceable language front-end: it returns the same typed
``GoalDraft``-shaped JSON as the deterministic tutorial parser.  GoalFinalizer
and Policy keep all authority over the resulting Goal.  There is deliberately
no fallback to a deterministic parser: a failed or unverifiable model output
raises so the operator sees the failure instead of silently changing
behaviour.  This module has no tool, shell, or Runtime execution port.

The Codex CLI is invoked without a response-schema file because the managed
relay's structured-output engine rejects dynamic-key objects such as
``interpretation``; the returned text is therefore constrained by the prompt
and decoded strictly here.  ``L1ModelBoundary`` still rejects unknown fields,
forbidden literals and changed request text, and ``GoalDraft.validate`` still
checks interpretation/source consistency, so an off-schema model reply cannot
reach the Goal.
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


class CodexGoalDraftProvider:
    """Ephemeral structured provider for GoalDraft and SemanticToolCall data."""

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
        if not isinstance(request, Mapping) or request.get("kind") not in {
                "goal_draft", "goal_draft_revision", "tool_proposal"}:
            raise ValueError("goal provider received an unsupported request kind")
        prompt = self._prompt(request)
        with tempfile.TemporaryDirectory(prefix="openroad-l1-goal-") as raw:
            env = {key: os.environ[key] for key in (
                "HOME", "USER", "LOGNAME", "PATH", "LANG", "LC_ALL", "TZ", "CODEX_HOME"
            ) if key in os.environ}
            returncode, text, detail = self._run_codex(prompt, raw, env)
            if returncode != 0 or not text:
                raise RuntimeError("Codex L1 goal provider returned no structured proposal"
                                   + (f": {detail}" if detail else ""))
        value = self._decode(text)
        if not isinstance(value, Mapping):
            raise RuntimeError("Codex L1 goal provider must return a JSON object")
        return value

    def _run_codex(self, prompt: str, cwd: str, env: Mapping[str, str]) -> tuple[int, str, str]:
        result = subprocess.run(
            [self.executable, "exec", "--ephemeral", "--ignore-rules",
             "--skip-git-repo-check", "--sandbox", "read-only", "--model", self.model,
             "--color", "never", "-"],
            input=prompt, cwd=cwd, env=dict(env), text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=self.timeout_seconds, check=False,
        )
        detail = "\n".join((result.stderr or "").splitlines()[-6:])
        return result.returncode, result.stdout or "", detail

    @staticmethod
    def _decode(text: str) -> Any:
        """Extract the single JSON object from the model reply, fail closed."""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```", 2)[1] if cleaned.count("```") >= 2 else cleaned
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise RuntimeError("Codex L1 goal provider returned invalid JSON")
        try:
            return json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError as exc:
            raise RuntimeError("Codex L1 goal provider returned invalid JSON") from exc

    def _prompt(self, request: Mapping[str, Any]) -> str:
        """One bounded instruction; the model may return typed JSON only."""
        if request.get("kind") == "tool_proposal":
            return self._tool_prompt(request)
        if request.get("kind") == "goal_draft_revision":
            context = (
                "REVISION of an existing draft. Keep request_text, interpretation and "
                "field_sources unchanged. Copy every existing question in the same order with "
                "the same question_id, field, prompt, blocking, and schema_version. Populate answers: for every supplied "
                "ANSWER whose question_id matches a kept question, add one answers entry "
                "{question_id, field (the same field as that question), value (the supplied "
                "value), schema_version: 1}. Add no other answers."
            )
        else:
            context = (
                "INITIAL parse of one natural-language EDA goal. Copy REQUIRED_QUESTIONS "
                "byte-for-byte in semantic content and array order: do not create, delete, rename, "
                "re-field, reword, reorder, or change blocking/schema_version. For a required "
                "question whose answer is explicitly stated in USER_REQUEST, add one typed answer "
                "using exactly that question_id and field. Leave every omitted fact unanswered. "
                "Never infer an answer merely from a question prompt."
            )
        instruction = (
            "You are a constrained EDA goal interpreter. Reply with exactly one JSON object and nothing else "
            "(no markdown fences, no prose). The object must contain only these keys: "
            "request_text (string, verbatim copy of USER_REQUEST), schema_version (integer 1), "
            "intent (one of diagnose/execute/optimize/compare/explain), "
            "questions (array of objects {question_id, field, prompt, blocking, schema_version}) where "
            "field is one of " + ",".join(_FIELD_VALUES) + ", "
            "answers (array of {question_id, field, value, schema_version}; each entry must match a "
            "question with the same question_id and field; otherwise empty), "
            "interpretation (object mapping interpreted field names to values) and "
            "field_sources (object with exactly the same keys as interpretation, each value one of "
            "user/operator_profile/safe_default/derived). "
            "Do not invent a design, toolchain or budget. Never emit commands, paths, credentials, tool "
            "names, or RTL source: this is a typed language draft only.\n\n"
            f"{context}\n"
            f"USER_REQUEST={json.dumps(request.get('request_text'), ensure_ascii=False)}\n"
            f"REQUIRED_QUESTIONS={json.dumps(request.get('required_questions'), ensure_ascii=False)}\n"
            f"PRIOR_DRAFT={json.dumps(request.get('prior_draft'), ensure_ascii=False)}\n"
            f"ANSWERS={json.dumps(request.get('answers'), ensure_ascii=False)}\n"
        )
        return instruction

    def _tool_prompt(self, request: Mapping[str, Any]) -> str:
        """Ask for one typed next action; never expose an execution language."""
        goal, state, knowledge = request.get("goal"), request.get("state"), request.get("knowledge")
        if not isinstance(goal, Mapping) or not isinstance(state, Mapping) or not isinstance(knowledge, list):
            raise ValueError("tool proposal request lacks typed Goal/State/knowledge")
        evidence = [item.get("evidence") for item in knowledge if isinstance(item, Mapping)]
        tools = goal.get("allowed_tools") or []
        return (
            "You are the untrusted planning component of an EDA workbench. Return exactly one JSON "
            "object and nothing else. You may propose one typed action; platform Policy and Runtime "
            "will validate it. Never emit shell, Tcl, Python, a filesystem path, an executable, an "
            "environment variable, or credentials. Use only facts in GOAL, STATE, and KNOWLEDGE.\n"
            "Output exactly {call,decision_summary,citations}. call must be "
            "{call_id,goal_id,state_id,tool,arguments,producer,evidence,schema_version}. "
            f"Copy call_id={json.dumps(request.get('call_id'))}, "
            f"goal_id={json.dumps(goal.get('goal_id'))}, state_id={json.dumps(state.get('state_id'))}, "
            f"producer={json.dumps(request.get('provider_id'))}, schema_version=1. "
            f"tool must be one of {json.dumps(tools)}. citations must contain one or more exact "
            f"objects selected from AVAILABLE_EVIDENCE={json.dumps(evidence)}; call.evidence must be "
            "a subset of citations. Arguments must match the selected typed tool and reference only "
            "run/proposal/artifact identifiers already present in STATE or KNOWLEDGE. Prefer inspecting "
            "measured facts before proposing a new EDA run. decision_summary must state the visible "
            "evidence-based reason, without hidden reasoning.\n"
            f"GOAL={json.dumps(goal, ensure_ascii=False)}\n"
            f"STATE={json.dumps(state, ensure_ascii=False)}\n"
            f"KNOWLEDGE={json.dumps(knowledge, ensure_ascii=False)}\n"
        )
