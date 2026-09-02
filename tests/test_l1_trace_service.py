from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from openroad_platform_contracts.agent_control import AgentBudget, DesignState
from openroad_platform_contracts.agent_control import SemanticToolCall, ToolName
from openroad_platform_contracts.l1_observation import RuntimeObservation
from openroad_platform_contracts.learning import EvidencePointer
from openroad_platform_scheduler.l1_state_reducer import L1StateReducer
from openroad_platform_scheduler.l1_trace_service import L1TraceService
from openroad_platform_scheduler.l1_trace_store import L1TraceStore


def _state() -> DesignState:
    return DesignState("state-1", "goal-1", 0, "running", None, {}, AgentBudget(2, 2, 300, 1))


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
        trace.record_policy("trace-1", before, cross_goal, verdict="allow", summary="no")
