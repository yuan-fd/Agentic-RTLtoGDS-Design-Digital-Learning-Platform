from __future__ import annotations

import pytest

from openroad_platform_contracts.agent_control import (
    AgentBudget,
    DesignGoal,
    DesignState,
    GoalPreference,
    QoRConstraint,
    SemanticToolCall,
    ToolName,
)
from openroad_platform_contracts.learning import EvidencePointer


def _goal() -> DesignGoal:
    return DesignGoal(
        goal_id="goal-1", project_id="project-1", design_id="design-1",
        platform="sky130hd", pdk_id="sky130hd", toolchain_id="pinned-toolchain",
        rtl_artifact=EvidencePointer("artifact:rtl", "a" * 64),
        preference=GoalPreference.PERFORMANCE,
        hard_constraints=(QoRConstraint("setup_wns_ns", ">=", 0.0),),
        allowed_stages=("synth", "place", "route", "finish"),
        allowed_parameters=("core_utilization_pct",), budget=AgentBudget(2, 2, 300, 1),
    )


def test_agent_control_contracts_round_trip_without_package_reverse_imports() -> None:
    goal = _goal()
    assert DesignGoal.from_dict(goal.to_dict()) == goal
    state = DesignState("state-1", goal.goal_id, 0, "new", None, {}, AgentBudget(2, 2, 300, 1))
    call = SemanticToolCall("call-1", goal.goal_id, state.state_id, ToolName.QUERY_TIMING,
                            {"run_id": "run-1", "limit": 20}, "l1-planner")
    assert DesignState.from_dict(state.to_dict()) == state
    assert SemanticToolCall.from_dict(call.to_dict()) == call


def test_agent_control_rejects_shell_and_invalid_stage() -> None:
    goal = _goal()
    call = SemanticToolCall("call-1", goal.goal_id, "state-1", ToolName.QUERY_TIMING,
                            {"run_id": "run-1", "shell": "make route"}, "l1-planner")
    with pytest.raises(ValueError, match="forbidden"):
        call.validate()
    with pytest.raises(ValueError, match="unsupported allowed_stages"):
        DesignGoal(**{**goal.__dict__, "allowed_stages": ("routing2",)}).validate()
