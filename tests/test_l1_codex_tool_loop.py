from __future__ import annotations

import json

import pytest

from apps.l1_workbench.service import WorkbenchService


class _StructuredCodex:
    provider_id = "codex-cli-l1-goal-v1"

    def __init__(self, tool="run_full_flow", arguments=None):
        self.tool = tool; self.arguments = dict(arguments or {})

    def complete(self, request):
        if request["kind"] == "goal_draft":
            return {"request_text": request["request_text"], "intent": "execute",
                    "questions": request["required_questions"], "answers": [], "interpretation": {},
                    "field_sources": {}, "schema_version": 1}
        if request["kind"] == "goal_draft_revision":
            return {"request_text": request["request_text"], "intent": "execute",
                    "questions": request["prior_draft"]["questions"],
                    "answers": request["answers"], "interpretation": {},
                    "field_sources": {}, "schema_version": 1}
        assert request["kind"] == "tool_proposal"
        citation = request["knowledge"][0]["evidence"]
        return {
            "call": {"call_id": request["call_id"],
                     "goal_id": request["goal"]["goal_id"],
                     "state_id": request["state"]["state_id"],
                     "tool": self.tool, "arguments": self.arguments,
                     "producer": self.provider_id, "evidence": [citation],
                     "schema_version": 1},
            "decision_summary": "Use the cited typed state to take one bounded action.",
            "citations": [citation],
        }


def test_codex_tool_proposal_runs_only_through_policy_runtime_and_feedback(tmp_path):
    service = WorkbenchService(tmp_path, model_provider="codex")
    service._codex_provider = _StructuredCodex()
    session = service.start("Run one bounded implementation flow.")
    session = service.answer(session.session_id, [{
        "question_id": "objective-1", "field": "objective",
        "value": "one audited bounded implementation flow",
    }])
    result = service.advance(session.session_id)
    call = result["model_proposal"]["call"]
    assert call["tool"] == "run_full_flow"
    assert call["producer"] == "codex-cli-l1-goal-v1"
    assert result["state"]["status"] == "observed"
    assert result["state"]["diagnosis"]["runtime_run_id"] == result["plan"]["run_id"]
    events = service.events(session.session_id)
    assert [event["kind"] for event in events][-3:] == [
        "policy_decided", "tool_receipt", "state_transition"]
    assert next(event for event in events if event["kind"] == "tool_called")[
        "facts"]["producer"] == "codex-cli-l1-goal-v1"


def test_codex_tool_proposal_cannot_change_runtime_assigned_identity_or_emit_shell(tmp_path):
    class _Forged(_StructuredCodex):
        def complete(self, request):
            value = super().complete(request)
            if request["kind"] == "tool_proposal":
                value["call"]["call_id"] = "model-picked-call"
            return value

    service = WorkbenchService(tmp_path / "identity", model_provider="codex")
    service._codex_provider = _Forged()
    session = service.start("Run one bounded implementation flow.")
    session = service.answer(session.session_id, [{
        "question_id": "objective-1", "field": "objective",
        "value": "one audited bounded implementation flow",
    }])
    with pytest.raises(ValueError, match="call identity"):
        service.advance(session.session_id)
    assert not service.runtime.store.list_runs()

    service = WorkbenchService(tmp_path / "shell", model_provider="codex")
    service._codex_provider = _StructuredCodex(arguments={"shell": "make finish"})
    session = service.start("Run one bounded implementation flow.")
    session = service.answer(session.session_id, [{
        "question_id": "objective-1", "field": "objective",
        "value": "one audited bounded implementation flow",
    }])
    with pytest.raises(ValueError, match="forbidden"):
        service.advance(session.session_id)
    assert not service.runtime.store.list_runs()


def test_codex_tool_loop_enforces_llm_budget_from_durable_trace(tmp_path):
    service = WorkbenchService(tmp_path, model_provider="codex")
    service._codex_provider = _StructuredCodex(tool="get_design_summary")
    session = service.start("Inspect the managed design.")
    session = service.answer(session.session_id, [{
        "question_id": "objective-1", "field": "objective",
        "value": "inspect the bounded managed design",
    }])
    for _ in range(4):
        service.advance(session.session_id)
    with pytest.raises(ValueError, match="LLM-call budget"):
        service.advance(session.session_id)
    events = service.events(session.session_id)
    assert len([event for event in events if event["kind"] == "tool_called"]) == 4


def test_codex_tool_knowledge_skips_trace_events_without_artifact_evidence(tmp_path):
    service = WorkbenchService(tmp_path, model_provider="codex")
    service._codex_provider = _StructuredCodex(tool="get_design_summary")
    session = service.start("Inspect the managed design after a parameter proposal.")
    session = service.answer(session.session_id, [{
        "question_id": "objective-1", "field": "objective",
        "value": "inspect the bounded managed design",
    }])

    # SET_FLOW_PARAMS is a durable proposal and deliberately has no artifact
    # evidence.  It must not be converted into a made-up EvidencePointer when
    # the next model request is assembled.
    service.set_flow_params(
        session.session_id, {"place_density": 0.5},
        "Record one typed parameter proposal without executing EDA.")
    result = service.advance(session.session_id)

    assert result["model_proposal"]["call"]["tool"] == "get_design_summary"
    assert result["plan"]["receipt"]["status"] == "completed"
