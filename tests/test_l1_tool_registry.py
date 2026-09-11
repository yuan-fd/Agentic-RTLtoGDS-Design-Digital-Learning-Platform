import pytest
from pathlib import Path
from openroad_platform_contracts.agent_control import AgentBudget, DesignGoal, DesignState, GoalPreference, QoRConstraint, SemanticToolCall, ToolName, ToolReceipt
from openroad_platform_contracts.learning import EvidencePointer
from openroad_platform_contracts.l1_tool_contract import TUTORIAL_L1_TOOLS
from openroad_platform_scheduler.l1_tool_registry import L1RuntimeToolRegistry, tutorial_l1_registry_contract

class _Bridge:
    @staticmethod
    def supported_tools(): return TUTORIAL_L1_TOOLS
    def execute(self, goal, state, call):
        return ToolReceipt(call.call_id, goal.goal_id, state.state_id, call.tool, "completed", {}, (EvidencePointer("artifact:receipt", "a" * 64),))

def _goal():
    return DesignGoal("goal-1", "project-1", "design-1", "platform-1", "pdk-1", "toolchain-1", EvidencePointer("artifact:rtl", "b" * 64), GoalPreference.BALANCED, (QoRConstraint("wns", ">=", 0),), ("route",), ("density",), AgentBudget(1, 1, 60), tuple(sorted(TUTORIAL_L1_TOOLS, key=lambda x: x.value)))

def test_registry_discovers_exactly_tutorial_tools_and_dispatches():
    registry = L1RuntimeToolRegistry(_Bridge())
    assert {item.name for item in registry.contract.definitions} == TUTORIAL_L1_TOOLS
    goal = _goal(); state = DesignState("state-1", "goal-1", 0, "running", None, {}, AgentBudget(1, 1, 60))
    call = SemanticToolCall("call-1", "goal-1", "state-1", ToolName.GET_DESIGN_SUMMARY, {}, "planner")
    assert registry.execute(goal, state, call).status == "completed"

def test_registry_rejects_incomplete_bridge_and_disallowed_tool():
    class _Partial:
        @staticmethod
        def supported_tools(): return frozenset()
    with pytest.raises(ValueError, match="complete tutorial"):
        L1RuntimeToolRegistry(_Partial())
    goal = _goal(); state = DesignState("state-1", "goal-1", 0, "running", None, {}, AgentBudget(1, 1, 60))
    call = SemanticToolCall("call-1", "goal-1", "state-1", ToolName.CREATE_EXPERIMENT, {"name": "legacy"}, "planner")
    with pytest.raises(ValueError, match="not allowed"):
        L1RuntimeToolRegistry(_Bridge()).execute(goal, state, call)

def test_active_api_does_not_use_legacy_l1_experiment_service():
    source = (Path(__file__).parents[1] / "apps" / "api" / "app.py").read_text()
    assert "L1ORFSToolService" not in source
    assert "ToolName.CREATE_EXPERIMENT" not in source

def test_registry_dispatches_every_fixed_tool_surface():
    bridge = _Bridge(); registry = L1RuntimeToolRegistry(bridge); goal = _goal()
    state = DesignState("state-1", "goal-1", 0, "running", None, {}, AgentBudget(1, 1, 60))
    arguments = {
        ToolName.GET_DESIGN_SUMMARY: {}, ToolName.QUERY_TIMING: {"run_id": "run-1"},
        ToolName.QUERY_CONGESTION: {"run_id": "run-1"}, ToolName.QUERY_DRC: {"run_id": "run-1"},
        ToolName.QUERY_POWER: {"run_id": "run-1"}, ToolName.QUERY_STAGE_METRICS: {"run_id": "run-1"},
        ToolName.QUERY_ARTIFACT_EXCERPT: {"run_id": "run-1", "artifact_id": "artifact-1", "max_bytes": 1},
        ToolName.QUERY_OPENROAD_KNOWLEDGE: {"query": "Explain DRT-0349", "purpose": "error_explanation", "top_k": 3},
        ToolName.SET_FLOW_PARAMS: {"values": {"density": 1}}, ToolName.RUN_STAGE: {"stage": "route"},
        ToolName.RUN_FULL_FLOW: {}, ToolName.COMPARE_RUNS: {"left_run_id": "run-1", "right_run_id": "run-2", "metrics": ["wns"]},
        ToolName.STOP_OR_ESCALATE: {"run_id": "run-1", "reason": "bounded stop"},
    }
    for index, tool in enumerate(TUTORIAL_L1_TOOLS):
        registry.execute(goal, state, SemanticToolCall(f"call-{index}", goal.goal_id, state.state_id, tool, arguments[tool], "planner"))

def test_registry_rejects_forged_receipt_identity():
    class _Forged(_Bridge):
        def execute(self, goal, state, call):
            return ToolReceipt("other-call", goal.goal_id, state.state_id, call.tool, "completed", {}, (EvidencePointer("artifact:receipt", "a" * 64),))
    goal = _goal(); state = DesignState("state-1", "goal-1", 0, "running", None, {}, AgentBudget(1, 1, 60))
    with pytest.raises(ValueError, match="does not match"):
        L1RuntimeToolRegistry(_Forged()).execute(goal, state, SemanticToolCall("call-1", goal.goal_id, state.state_id, ToolName.GET_DESIGN_SUMMARY, {}, "planner"))
