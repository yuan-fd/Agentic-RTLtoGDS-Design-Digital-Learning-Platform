"""Policy denials are durable, visible trace verdicts, not silent errors."""
from openroad_platform_contracts.agent_control import AgentBudget, DesignGoal, DesignState, GoalPreference, QoRConstraint, SemanticToolCall, ToolName, ToolReceipt
from openroad_platform_contracts.learning import EvidencePointer
from openroad_platform_contracts.l1_policy import TrustedPolicyIdentity
from openroad_platform_contracts.l1_tool_contract import TUTORIAL_L1_TOOLS
from openroad_platform_scheduler.l1_loop import L1DurableLoop
from openroad_platform_scheduler.l1_loop_store import L1LoopStore
from openroad_platform_scheduler.l1_trace_service import L1TraceService
from openroad_platform_scheduler.l1_trace_store import L1TraceStore
import pytest


def _policy():
    return TrustedPolicyIdentity("policy-1", "v1", "platform", EvidencePointer("artifact:policy", "d" * 64))


def _goal(allowed_tools=(), budget=(1, 2, 60)):
    labels = {"l1_policy_id": "policy-1", "l1_policy_version": "v1", "l1_policy_issuer": "platform",
              "l1_policy_provenance": "artifact:policy", "l1_policy_provenance_sha256": "d" * 64}
    return DesignGoal("goal-1", "p1", "top", "platform-1", "pdk-1", "toolchain-1",
                      EvidencePointer("artifact:rtl", "a" * 64), GoalPreference.BALANCED,
                      (QoRConstraint("setup_wns_ns", ">=", 0),), ("route",), ("density",),
                      AgentBudget(*budget), allowed_tools=tuple(allowed_tools), labels=labels)


class _Bridge:
    @staticmethod
    def supported_tools():
        return TUTORIAL_L1_TOOLS

    def execute(self, goal, state, call):
        return ToolReceipt(call.call_id, goal.goal_id, state.state_id, call.tool, "accepted",
                           {"run_id": "run-1"}, (EvidencePointer("run:run-1", "e" * 64),))


def test_budget_exhaustion_records_a_visible_policy_denial(tmp_path):
    goal = _goal(allowed_tools=(ToolName.RUN_FULL_FLOW,))
    state = DesignState("state-1", "goal-1", 0, "running", None, {}, AgentBudget(0, 2, 60))
    trace = L1TraceService(L1TraceStore(tmp_path / "trace.sqlite"))
    trace.record_goal("trace-1", goal)
    call = SemanticToolCall("call-1", "goal-1", "state-1", ToolName.RUN_FULL_FLOW, {}, "planner")
    with pytest.raises(ValueError, match="budget"):
        L1DurableLoop(L1LoopStore(tmp_path / "loop.sqlite"), _Bridge(), trace).plan_validate_execute(
            "trace-1", goal, state, call, _policy(), planner_summary="no budget")
    events = trace.store.read("trace-1")
    assert [event.kind.value for event in events] == ["goal_finalized", "tool_called", "policy_decided"]
    denial = events[-1]
    assert denial.policy_verdict == "deny"
    assert denial.tool is ToolName.RUN_FULL_FLOW
    assert "budget" in (denial.planner_summary or "")


def test_unsupported_tool_records_a_visible_policy_denial_before_runtime(tmp_path):
    goal = _goal(allowed_tools=(ToolName.RUN_FULL_FLOW,))
    state = DesignState("state-1", "goal-1", 0, "running", None, {}, AgentBudget(1, 2, 60))
    trace = L1TraceService(L1TraceStore(tmp_path / "trace.sqlite"))
    trace.record_goal("trace-1", goal)
    call = SemanticToolCall("call-1", "goal-1", "state-1", ToolName.QUERY_TIMING, {"run_id": "run-1"}, "planner")
    with pytest.raises(ValueError):
        L1DurableLoop(L1LoopStore(tmp_path / "loop.sqlite"), _Bridge(), trace).plan_validate_execute(
            "trace-1", goal, state, call, _policy(), planner_summary="unregistered tool")
    events = trace.store.read("trace-1")
    assert events[-1].kind.value == "policy_decided"
    assert events[-1].policy_verdict == "deny"
    assert events[-1].tool is ToolName.QUERY_TIMING


def test_schema_invalid_call_keeps_the_original_error_and_no_false_verdict(tmp_path):
    goal = _goal(allowed_tools=(ToolName.RUN_FULL_FLOW,))
    state = DesignState("state-1", "goal-1", 0, "running", None, {}, AgentBudget(1, 2, 60))
    trace = L1TraceService(L1TraceStore(tmp_path / "trace.sqlite"))
    trace.record_goal("trace-1", goal)
    call = SemanticToolCall("call-1", "goal-1", "state-1", ToolName.RUN_FULL_FLOW, {"shell": "bad"}, "planner")
    with pytest.raises(ValueError, match="arguments"):
        L1DurableLoop(L1LoopStore(tmp_path / "loop.sqlite"), _Bridge(), trace).plan_validate_execute(
            "trace-1", goal, state, call, _policy(), planner_summary="bad")
    assert [event.kind.value for event in trace.store.read("trace-1")] == ["goal_finalized"]
