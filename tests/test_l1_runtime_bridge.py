from types import SimpleNamespace

from openroad_platform_contracts.agent_control import AgentBudget, DesignGoal, DesignState, GoalPreference, QoRConstraint, SemanticToolCall, ToolName
from openroad_platform_contracts.learning import EvidencePointer
from openroad_platform_execution.orfs_task_factory import ORFSRTLToGDSFactory
from openroad_platform_execution.orfs_plugin import build_orfs_task
from openroad_platform_scheduler.l1_runtime_bridge import L1RuntimeBridge


class _Runtime:
    def submit(self, task, *, capability): self.task, self.capability = task, capability; return SimpleNamespace(run_id="run-1")
    def describe(self, run_id): return {"run": {"status": "succeeded"}, "stages": [{"stage_key": "route", "successful_attempt_id": "attempt-1", "attempts": [{"attempt_id": "attempt-1", "metrics": [{"name": "setup_wns_ns", "value": -0.1}], "artifacts": [{"artifact_id": "report-1"}]}]}]}


def test_runtime_bridge_only_submits_immutable_task_and_observes_runtime(tmp_path):
    rtl = tmp_path / "top.v"; rtl.write_text("module top; endmodule\n")
    runtime = _Runtime(); bridge = L1RuntimeBridge(runtime, build_orfs_task(rtl, project_id="p1", design_id="top"), ORFSRTLToGDSFactory())
    goal = DesignGoal("goal-1", "p1", "top", "nangate45", "pdk-1", "toolchain-1", EvidencePointer("artifact:rtl", "a" * 64), GoalPreference.BALANCED, (QoRConstraint("setup_wns_ns", ">=", 0),), ("route",), ("core_utilization_pct",), AgentBudget(2, 2, 60))
    state = DesignState("state-1", "goal-1", 0, "running", None, {}, AgentBudget(2, 2, 60))
    receipt = bridge.submit(goal, state, SemanticToolCall("call-1", "goal-1", "state-1", ToolName.RUN_STAGE, {"stage": "route"}, "planner"))
    assert receipt.status == "accepted" and runtime.task.parameters["target_stage"] == "route"
    assert bridge.observation("run-1").attempt_id == "attempt-1"
