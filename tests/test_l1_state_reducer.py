from __future__ import annotations

import pytest

from openroad_platform_contracts.agent_control import AgentBudget, DesignState
from openroad_platform_contracts.l1_observation import RuntimeObservation
from openroad_platform_contracts.learning import EvidencePointer
from openroad_platform_scheduler.l1_state_reducer import L1StateReducer


def _state(status: str = "running") -> DesignState:
    return DesignState("state-1", "goal-1", 0, status, None, {}, AgentBudget(2, 2, 300, 1))


def _observation(status: str = "succeeded") -> RuntimeObservation:
    return RuntimeObservation("run-1", "attempt-1", "route", status, {"setup_wns_ns": -0.1},
                              (EvidencePointer("artifact:route", "a" * 64),))


def test_reducer_advances_only_from_evidence_backed_runtime_observation() -> None:
    result = L1StateReducer.apply(_state(), _observation(), next_state_id="state-2")
    assert result.parent_state_id == "state-1"
    assert result.status == "observed"
    assert result.diagnosis["runtime_run_id"] == "run-1"


def test_reducer_preserves_runtime_failure_and_rejects_terminal_injection() -> None:
    assert L1StateReducer.apply(_state(), _observation("failed"), next_state_id="state-2").status == "failed"
    with pytest.raises(ValueError, match="terminal"):
        L1StateReducer.apply(_state("completed"), _observation(), next_state_id="state-2")
