from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from openroad_platform_contracts.agent_control import AgentBudget, DesignGoal, DesignState, GoalPreference, QoRConstraint
from openroad_platform_contracts.agent_control import SemanticToolCall, ToolName, ToolReceipt
from openroad_platform_contracts.l1_observation import RuntimeObservation
from openroad_platform_contracts.l1_policy import TrustedPolicyIdentity
from openroad_platform_contracts.learning import EvidencePointer
from openroad_platform_scheduler.l1_state_reducer import L1StateReducer
from openroad_platform_scheduler.l1_trace_service import L1TraceService
from openroad_platform_scheduler.l1_trace_store import L1TraceStore


def _state() -> DesignState:
    return DesignState("state-1", "goal-1", 0, "running", None, {}, AgentBudget(2, 2, 300, 1))


def _goal() -> DesignGoal:
    return DesignGoal("goal-1", "project-1", "design-1", "platform-1", "pdk-1", "toolchain-1",
                      EvidencePointer("artifact:rtl", "c" * 64), GoalPreference.BALANCED,
                      (QoRConstraint("setup_wns_ns", ">=", 0.0),), ("route",), ("density",), AgentBudget(2, 2, 300, 1),
                      labels={"l1_policy_id": "policy-1", "l1_policy_version": "v1", "l1_policy_issuer": "platform",
                              "l1_policy_provenance": "artifact:policy", "l1_policy_provenance_sha256": "d" * 64})


def _policy() -> TrustedPolicyIdentity:
    return TrustedPolicyIdentity("policy-1", "v1", "platform", EvidencePointer("artifact:policy", "d" * 64))


def test_trace_service_records_runtime_lineage_with_state_hashes(tmp_path: Path) -> None:
    trace = L1TraceService(L1TraceStore(tmp_path / "trace.sqlite"),
                           clock=lambda: datetime(2026, 9, 2, tzinfo=timezone.utc))
    before = _state()
    observation = RuntimeObservation("run-1", "attempt-1", "route", "succeeded", {"setup_wns_ns": -0.1},
                                     (EvidencePointer("artifact:route", "a" * 64),))
    after = L1StateReducer.apply(before, observation, next_state_id="state-2")
    event = trace.record_observation("trace-1", before, after, observation)
    assert event.state_before_sha256 != event.state_after_sha256
    stored = trace.store.read("trace-1")
    assert stored[0].facts["run_id"] == "run-1"


def test_trace_service_rejects_forged_observation_successor_and_cross_state_policy(tmp_path: Path) -> None:
    trace = L1TraceService(L1TraceStore(tmp_path / "trace.sqlite"))
    before = _state()
    observation = RuntimeObservation("run-1", "attempt-1", "route", "succeeded", {"setup_wns_ns": -0.1},
                                     (EvidencePointer("artifact:route", "a" * 64),))
    forged = DesignState("state-2", "goal-1", 1, "completed", "route", {"setup_wns_ns": 99.0}, before.remaining_budget,
                         evidence=(EvidencePointer("artifact:forged", "b" * 64),), parent_state_id="state-1")
    import pytest
    with pytest.raises(ValueError, match="canonical reducer"):
        trace.record_observation("trace-1", before, forged, observation)
    cross_goal = SemanticToolCall("call-1", "other-goal", "state-1", ToolName.QUERY_TIMING, {"run_id": "run-1"}, "planner")
    with pytest.raises(ValueError, match="policy call"):
        trace.record_policy("trace-1", _goal(), before, cross_goal, _policy(), verdict="allow", summary="no")


def test_trace_receipt_cannot_advance_state_and_policy_must_match_goal(tmp_path: Path) -> None:
    trace = L1TraceService(L1TraceStore(tmp_path / "trace.sqlite")); state = _state(); goal = _goal()
    call = SemanticToolCall("call-1", "goal-1", "state-1", ToolName.QUERY_TIMING, {"run_id": "run-1"}, "planner")
    wrong = TrustedPolicyIdentity("policy-2", "v1", "platform", EvidencePointer("artifact:policy", "d" * 64))
    import pytest
    with pytest.raises(ValueError, match="identity"):
        trace.record_policy("trace-1", goal, state, call, wrong, verdict="allow", summary="no")
    with pytest.raises(ValueError, match="finalized Goal"):
        trace.record_policy("trace-1", goal, state, call, _policy(), verdict="allow", summary="no")
    trace.record_goal("trace-1", goal)
    with pytest.raises(ValueError, match="prior matching tool call"):
        trace.record_policy("trace-1", goal, state, call, _policy(), verdict="allow", summary="no")
    trace.record_call("trace-1", state, call, planner_summary="query")
    policy_event = trace.record_policy("trace-1", goal, state, call, _policy(), verdict="allow", summary="ok")
    assert policy_event.facts["policy"]["policy_id"] == "policy-1"
    receipt = ToolReceipt("call-1", "goal-1", "state-1", ToolName.QUERY_TIMING, "completed", {}, (EvidencePointer("run:run-1", "e" * 64),), "forged-state")
    event = trace.record_receipt("trace-1", state, receipt)
    assert event.state_before_sha256 == event.state_after_sha256


def test_trace_service_rejects_forked_or_stale_stateful_events(tmp_path: Path) -> None:
    import pytest
    trace = L1TraceService(L1TraceStore(tmp_path / "trace.sqlite")); before = _state()
    first = RuntimeObservation("run-1", "attempt-1", "route", "succeeded", {"setup_wns_ns": -0.1},
                               (EvidencePointer("artifact:route-1", "a" * 64),))
    after = L1StateReducer.apply(before, first, next_state_id="state-a")
    trace.record_observation("trace-1", before, after, first)
    second = RuntimeObservation("run-2", "attempt-2", "route", "succeeded", {"setup_wns_ns": 0.1},
                                (EvidencePointer("artifact:route-2", "b" * 64),))
    fork = L1StateReducer.apply(before, second, next_state_id="state-b")
    with pytest.raises(ValueError, match="stale or forked"):
        trace.record_observation("trace-1", before, fork, second)
    stale = SemanticToolCall("call-stale", "goal-1", "state-1", ToolName.QUERY_TIMING, {"run_id": "run-1"}, "planner")
    with pytest.raises(ValueError, match="stale or forked"):
        trace.record_call("trace-1", before, stale, planner_summary="stale")
