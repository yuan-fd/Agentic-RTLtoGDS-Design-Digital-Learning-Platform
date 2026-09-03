from __future__ import annotations

import pytest

from openroad_platform_contracts import (
    AgentBudget, DesignGoal, DesignState, EvidencePointer, GoalPreference,
    QoRConstraint, SemanticToolCall, ToolName, ToolReceipt,
)
from openroad_platform_scheduler.semantic_tools import (
    SemanticToolRegistry, ToolDefinition,
)


def _evidence(ref: str = "artifact:rtl") -> EvidencePointer:
    return EvidencePointer(ref=ref, sha256="a" * 64)


def _goal() -> DesignGoal:
    return DesignGoal(
        goal_id="goal-1", project_id="project-1", design_id="aes",
        platform="sky130hd", pdk_id="sky130hd", toolchain_id="orfs-pinned",
        rtl_artifact=_evidence(), preference=GoalPreference.BALANCED,
        hard_constraints=(
            QoRConstraint("setup_wns_ns", ">=", 0.0),
            QoRConstraint("drc_errors", "==", 0.0),
        ),
        allowed_stages=("synth", "floorplan", "place", "cts", "route", "finish"),
        allowed_parameters=("core_utilization_pct", "cts_cluster_size"),
        budget=AgentBudget(20, 30, 3600, 2),
    )


def _state(status: str = "observed") -> DesignState:
    return DesignState(
        state_id="state-1", goal_id="goal-1", revision=1, status=status,
        completed_stage="cts", metrics={"setup_wns_ns": -0.1},
        remaining_budget=AgentBudget(19, 29, 3500, 2), evidence=(_evidence("artifact:report"),),
    )


def _receipt(goal, state, call) -> ToolReceipt:
    return ToolReceipt(
        call_id=call.call_id, goal_id=goal.goal_id, state_id=state.state_id,
        tool=call.tool, status="completed", result={"summary": "ok"},
        evidence=(_evidence("artifact:tool-result"),),
        next_state_id="state-2" if call.tool not in {
            ToolName.QUERY_TIMING, ToolName.QUERY_CONGESTION, ToolName.QUERY_DRC,
            ToolName.QUERY_POWER, ToolName.QUERY_ARTIFACT_EXCERPT,
            ToolName.COMPARE_RUNS,
        } else None,
    )


def _registry(*tools: ToolName) -> SemanticToolRegistry:
    registry = SemanticToolRegistry()
    for tool in tools:
        registry.register(ToolDefinition(tool, tool not in {
            ToolName.QUERY_TIMING, ToolName.QUERY_CONGESTION, ToolName.QUERY_DRC,
            ToolName.QUERY_POWER, ToolName.QUERY_ARTIFACT_EXCERPT,
            ToolName.COMPARE_RUNS,
        }, _receipt))
    return registry


def test_goal_state_and_call_round_trip_are_strict():
    goal = _goal(); state = _state()
    assert DesignGoal.from_dict(goal.to_dict()) == goal
    assert DesignState.from_dict(state.to_dict()) == state
    call = SemanticToolCall("call-1", "goal-1", "state-1", ToolName.RUN_STAGE,
                            {"stage": "finish", "experiment_id": "experiment-1"}, "policy")
    assert SemanticToolCall.from_dict(call.to_dict()) == call
    payload = call.to_dict(); payload["arguments"]["shell"] = "rm -rf /"
    with pytest.raises(ValueError, match="Unknown|forbidden"):
        SemanticToolCall.from_dict(payload)


def test_gate_accepts_typed_run_and_preserves_receipt_identity():
    goal = _goal(); state = _state(); registry = _registry(ToolName.RUN_STAGE)
    call = SemanticToolCall("call-1", goal.goal_id, state.state_id, ToolName.RUN_STAGE,
                            {"stage": "finish", "experiment_id": "experiment-1"}, "policy")
    receipt = registry.execute(goal, state, call)
    assert receipt.status == "completed"
    assert receipt.next_state_id == "state-2"


def test_gate_rejects_unknown_parameter_and_terminal_mutation():
    goal = _goal(); registry = _registry(ToolName.SET_FLOW_PARAMS)
    unknown = SemanticToolCall("call-2", goal.goal_id, "state-1", ToolName.SET_FLOW_PARAMS,
                               {"experiment_id": "experiment-1", "values": {"evil_parameter": 1}}, "policy")
    with pytest.raises(ValueError, match="unallowlisted"):
        registry.execute(goal, _state(), unknown)
    terminal = SemanticToolCall("call-3", goal.goal_id, "state-1", ToolName.SET_FLOW_PARAMS,
                                {"experiment_id": "experiment-1", "values": {"core_utilization_pct": 60}}, "policy")
    with pytest.raises(ValueError, match="terminal"):
        registry.execute(goal, _state("completed"), terminal)


def test_read_only_tool_cannot_forge_successor_state():
    goal = _goal(); state = _state()

    def bad_handler(goal, state, call):
        return ToolReceipt(call.call_id, goal.goal_id, state.state_id, call.tool,
                           "completed", {"summary": "bad"}, (_evidence("artifact:q"),),
                           next_state_id="state-2")

    registry = SemanticToolRegistry()
    registry.register(ToolDefinition(ToolName.QUERY_TIMING, False, bad_handler))
    call = SemanticToolCall("call-4", goal.goal_id, state.state_id, ToolName.QUERY_TIMING,
                            {"run_id": "run-1", "limit": 10}, "policy")
    with pytest.raises(ValueError, match="read-only"):
        registry.execute(goal, state, call)
