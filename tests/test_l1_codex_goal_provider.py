"""Offline tests for the managed Codex L1 GoalDraft provider."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "apps" / "l1_workbench"))

from codex_goal_provider import CodexGoalDraftProvider  # noqa: E402
from openroad_platform_contracts.l1_goal_draft import GoalDraft  # noqa: E402
from openroad_platform_scheduler.l1_model_boundary import L1ModelBoundary  # noqa: E402

_USER_TEXT = "Help improve mux setup timing, area must not rise more than 3%."


def _payload(text=_USER_TEXT, *, with_blocking=True):
    questions = [{"question_id": "design_context", "field": "design_context",
                  "prompt": "Confirm the managed baseline and timing corner.",
                  "blocking": with_blocking, "schema_version": 1}]
    return {
        "request_text": text,
        "schema_version": 1,
        "intent": "optimize",
        "questions": questions,
        "answers": [],
        "interpretation": {"intent": "optimize", "metric": "setup_wns_ns"},
        "field_sources": {"intent": "user", "metric": "user"},
    }


def _make_provider(tmp_path, payload, *, returncode=0):
    provider = CodexGoalDraftProvider(executable="/bin/echo")

    def fake_run(prompt, cwd, env):
        text = json.dumps(payload) if payload is not None else ""
        return returncode, text, "boom" if returncode else ""

    provider._run_codex = fake_run  # type: ignore[assignment]
    return provider


def test_codex_provider_produces_a_bound_goal_draft(tmp_path):
    provider = _make_provider(tmp_path, _payload(with_blocking=True))
    draft = L1ModelBoundary.compile_draft(provider, _USER_TEXT, draft_id="draft-1")
    assert isinstance(draft, GoalDraft)
    assert draft.request_text == _USER_TEXT
    assert draft.parser_id == "codex-cli-l1-goal-v1"
    assert len(draft.questions) == 1
    assert draft.unresolved_blocking_fields()


def test_codex_provider_clean_draft_has_no_unresolved_blocking_fields(tmp_path):
    payload = _payload(with_blocking=False)
    provider = _make_provider(tmp_path, payload)
    draft = L1ModelBoundary.compile_draft(provider, _USER_TEXT, draft_id="draft-2")
    assert draft.unresolved_blocking_fields() == ()


def test_codex_provider_rejects_forbidden_or_unknown_fields(tmp_path):
    payload = _payload()
    payload["command"] = "rm -rf /"
    provider = _make_provider(tmp_path, payload)
    with pytest.raises(ValueError):
        L1ModelBoundary.compile_draft(provider, _USER_TEXT, draft_id="draft-3")


def test_codex_provider_rejects_changed_request_text(tmp_path):
    payload = _payload(text="a completely different sentence")
    provider = _make_provider(tmp_path, payload)
    with pytest.raises(ValueError, match="changed the user request"):
        L1ModelBoundary.compile_draft(provider, _USER_TEXT, draft_id="draft-4")


def test_codex_provider_raises_when_no_structured_proposal(tmp_path):
    provider = _make_provider(tmp_path, None, returncode=1)
    with pytest.raises(RuntimeError, match="no structured proposal"):
        provider.complete({"kind": "goal_draft", "request_text": _USER_TEXT})


def test_codex_provider_raises_on_invalid_json(tmp_path):
    provider = CodexGoalDraftProvider(executable="/bin/echo")

    def fake_bad(prompt, cwd, env):
        return 0, "{not json", ""

    provider._run_codex = fake_bad  # type: ignore[assignment]
    with pytest.raises(RuntimeError, match="invalid JSON"):
        provider.complete({"kind": "goal_draft", "request_text": _USER_TEXT})


def test_codex_provider_fails_closed_when_cli_is_unavailable(monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(FileNotFoundError, match="codex CLI"):
        CodexGoalDraftProvider()


def test_codex_provider_rejects_non_allowlisted_model():
    with pytest.raises(ValueError, match="allowlisted"):
        CodexGoalDraftProvider(executable="/bin/echo", model="gpt-unknown")
