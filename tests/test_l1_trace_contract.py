from __future__ import annotations

import pytest

from openroad_platform_contracts.agent_control import ToolName
from openroad_platform_contracts.l1_trace import L1TraceEvent, TraceEventKind
from openroad_platform_contracts.learning import EvidencePointer


def _event(kind: TraceEventKind = TraceEventKind.TOOL_RECEIPT) -> L1TraceEvent:
    return L1TraceEvent(
        trace_id="trace-1", event_id="event-1", sequence=1, kind=kind, goal_id="goal-1",
        occurred_at="2026-09-02T12:00:00+00:00", state_before_sha256="a" * 64,
        state_after_sha256="b" * 64, planner_summary="Query timing before choosing a mutation.",
        tool=ToolName.QUERY_TIMING, policy_verdict="allow", facts={"wns": -0.1},
        hypotheses={"reason": "possible data-path issue"},
        evidence=(EvidencePointer("artifact:timing", "c" * 64),),
    )


def test_trace_event_is_round_trippable_and_evidence_backed() -> None:
    event = _event()
    assert L1TraceEvent.from_dict(event.to_dict()) == event


@pytest.mark.parametrize("field,value", [
    ("facts", {"shell": "make route"}),
    ("hypotheses", {"hidden_reasoning": "private"}),
    ("occurred_at", "2026-09-02T12:00:00"),
])
def test_trace_event_rejects_execution_and_hidden_reasoning_surfaces(field, value) -> None:
    with pytest.raises(ValueError):
        L1TraceEvent(**{**_event().__dict__, field: value}).validate()


def test_policy_and_receipt_events_require_their_respective_evidence() -> None:
    with pytest.raises(ValueError, match="requires a verdict"):
        L1TraceEvent(**{**_event(TraceEventKind.POLICY_DECIDED).__dict__, "policy_verdict": None}).validate()
    with pytest.raises(ValueError, match="requires evidence"):
        L1TraceEvent(**{**_event().__dict__, "evidence": ()}).validate()
