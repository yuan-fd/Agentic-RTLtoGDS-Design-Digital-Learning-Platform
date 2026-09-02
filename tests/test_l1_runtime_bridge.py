from types import SimpleNamespace
import platform
import sys
from pathlib import Path

from openroad_platform_contracts.agent_control import AgentBudget, DesignGoal, DesignState, GoalPreference, QoRConstraint, SemanticToolCall, ToolName
from openroad_platform_contracts.l1_tool_contract import TUTORIAL_L1_TOOLS
from openroad_platform_contracts.learning import EvidencePointer
from openroad_platform_execution.orfs_task_factory import ORFSRTLToGDSFactory
from openroad_platform_execution.orfs_plugin import build_orfs_task
from openroad_platform_execution import PluginRegistry, ProcessAdapter, ProcessGuardian
from openroad_platform_contracts import PluginManifest, TaskSpec
from openroad_platform_scheduler.runtime import WorkflowRuntime
from openroad_platform_scheduler.runtime_store import RuntimeStore
from openroad_platform_scheduler.l1_runtime_bridge import L1RuntimeBridge
from openroad_platform_scheduler.l1_trace_service import L1TraceService
from openroad_platform_scheduler.l1_trace_store import L1TraceStore
from openroad_platform_scheduler.l1_loop import L1DurableLoop
from openroad_platform_scheduler.l1_loop_store import L1LoopStore
from openroad_platform_contracts.l1_policy import TrustedPolicyIdentity


class _Runtime:
    def __init__(self): self.cancelled = []
    def submit(self, task, *, capability): self.task, self.capability = task, capability; return SimpleNamespace(run_id="run-1")
    def request_cancel(self, run_id): self.cancelled.append(run_id)
    def read_artifact_excerpt(self, run_id, artifact_id, *, offset, max_bytes): raise ValueError("artifact is not registered in the specified Runtime run")
    def describe(self, run_id): return {"run": {"status": "succeeded", "task_spec": {"labels": {"l1_goal_id": "goal-1"}}}, "stages": [{"stage_key": "route", "successful_attempt_id": "attempt-1", "attempts": [{"attempt_id": "attempt-1", "metrics": [{"name": "setup_wns_ns", "value": -0.1}], "artifacts": [{"artifact_id": "report-1"}]}]}]}


def test_runtime_bridge_only_submits_immutable_task_and_observes_runtime(tmp_path):
    rtl = tmp_path / "top.v"; rtl.write_text("module top; endmodule\n")
    runtime = _Runtime(); bridge = L1RuntimeBridge(runtime, build_orfs_task(rtl, project_id="p1", design_id="top"), ORFSRTLToGDSFactory())
    goal = DesignGoal("goal-1", "p1", "top", "nangate45", "pdk-1", "toolchain-1", EvidencePointer("artifact:rtl", "a" * 64), GoalPreference.BALANCED, (QoRConstraint("setup_wns_ns", ">=", 0),), ("route",), ("core_utilization_pct",), AgentBudget(2, 2, 60))
    state = DesignState("state-1", "goal-1", 0, "running", None, {}, AgentBudget(2, 2, 60))
    receipt = bridge.submit(goal, state, SemanticToolCall("call-1", "goal-1", "state-1", ToolName.RUN_STAGE, {"stage": "route"}, "planner"))
    assert receipt.status == "accepted" and runtime.task.parameters["target_stage"] == "route"
    assert bridge.observation("run-1").attempt_id == "attempt-1"
    successor = bridge.reduce_and_trace(L1TraceService(L1TraceStore(tmp_path / "trace.sqlite")), "trace-1", state, run_id="run-1", next_state_id="state-2")
    assert successor.metrics["setup_wns_ns"] == -0.1


def test_runtime_bridge_has_no_memory_experiment_state_and_handles_tutorial_controls(tmp_path):
    rtl = tmp_path / "top.v"; rtl.write_text("module top; endmodule\n")
    runtime = _Runtime(); bridge = L1RuntimeBridge(runtime, build_orfs_task(rtl, project_id="p1", design_id="top"), ORFSRTLToGDSFactory())
    goal = DesignGoal("goal-1", "p1", "top", "nangate45", "pdk-1", "toolchain-1", EvidencePointer("artifact:rtl", "a" * 64), GoalPreference.BALANCED, (QoRConstraint("setup_wns_ns", ">=", 0),), ("route",), ("core_utilization_pct",), AgentBudget(2, 2, 60))
    state = DesignState("state-1", "goal-1", 0, "running", None, {}, AgentBudget(2, 2, 60))
    summary = bridge.execute(goal, state, SemanticToolCall("call-2", "goal-1", "state-1", ToolName.GET_DESIGN_SUMMARY, {}, "planner"))
    assert summary.result["design_id"] == "top"
    patch = bridge.execute(goal, state, SemanticToolCall("call-3", "goal-1", "state-1", ToolName.SET_FLOW_PARAMS, {"values": {"core_utilization_pct": 30}}, "planner"))
    assert patch.status == "accepted" and patch.result["requires_following_run"] is True
    assert not hasattr(bridge, "_experiments") and not hasattr(bridge, "_states")
    assert bridge.supported_tools() == TUTORIAL_L1_TOOLS


def test_runtime_bridge_enforces_goal_policy_and_runtime_artifact_read_contract(tmp_path):
    import pytest
    rtl = tmp_path / "top.v"; rtl.write_text("module top; endmodule\n")
    runtime = _Runtime(); bridge = L1RuntimeBridge(runtime, build_orfs_task(rtl, project_id="p1", design_id="top"), ORFSRTLToGDSFactory())
    goal = DesignGoal("goal-1", "p1", "top", "nangate45", "pdk-1", "toolchain-1", EvidencePointer("artifact:rtl", "a" * 64), GoalPreference.BALANCED, (QoRConstraint("setup_wns_ns", ">=", 0),), ("route",), ("core_utilization_pct",), AgentBudget(2, 2, 60), allowed_tools=(ToolName.QUERY_TIMING, ToolName.QUERY_ARTIFACT_EXCERPT))
    state = DesignState("state-1", "goal-1", 0, "running", None, {}, AgentBudget(2, 2, 60))
    with pytest.raises(ValueError, match="not allowed"):
        bridge.execute(goal, state, SemanticToolCall("call-4", "goal-1", "state-1", ToolName.GET_DESIGN_SUMMARY, {}, "planner"))
    with pytest.raises(ValueError, match="registered"):
        bridge.execute(goal, state, SemanticToolCall("call-5", "goal-1", "state-1", ToolName.QUERY_ARTIFACT_EXCERPT, {"run_id": "run-1", "artifact_id": "wrong", "max_bytes": 10}, "planner"))


def test_runtime_bridge_rejects_foreign_query_and_accepts_runtime_timeout_attempt(tmp_path):
    import pytest
    rtl = tmp_path / "top.v"; rtl.write_text("module top; endmodule\n")
    runtime = _Runtime(); bridge = L1RuntimeBridge(runtime, build_orfs_task(rtl, project_id="p1", design_id="top"), ORFSRTLToGDSFactory())
    goal = DesignGoal("goal-1", "p1", "top", "nangate45", "pdk-1", "toolchain-1", EvidencePointer("artifact:rtl", "a" * 64), GoalPreference.BALANCED, (QoRConstraint("setup_wns_ns", ">=", 0),), ("route",), ("core_utilization_pct",), AgentBudget(2, 2, 60), allowed_tools=(ToolName.QUERY_TIMING,))
    state = DesignState("state-1", "goal-1", 0, "running", None, {}, AgentBudget(2, 2, 60))
    runtime.describe = lambda run_id: {"run": {"status": "failed", "terminal_reason": "timed_out", "task_spec": {"labels": {"l1_goal_id": "other-goal"}}}, "stages": [{"stage_key": "route", "attempts": [{"attempt_id": "attempt-timeout", "status": "timed_out", "metrics": [], "artifacts": []}]}]}
    with pytest.raises(ValueError, match="not owned"):
        bridge.execute(goal, state, SemanticToolCall("call-foreign", "goal-1", "state-1", ToolName.QUERY_TIMING, {"run_id": "foreign"}, "planner"))
    with pytest.raises(ValueError, match="not owned"):
        bridge.reduce_and_trace(L1TraceService(L1TraceStore(tmp_path / "foreign.sqlite")), "trace-foreign", state, run_id="foreign", next_state_id="state-2")
    runtime.describe = lambda run_id: {"run": {"status": "failed", "terminal_reason": "timed_out", "task_spec": {"labels": {"l1_goal_id": "goal-1"}}}, "stages": [{"stage_key": "route", "attempts": [{"attempt_id": "attempt-timeout", "status": "timed_out", "metrics": [], "artifacts": []}]}]}
    timeout = bridge.observation("run-timeout")
    assert timeout.attempt_id == "attempt-timeout" and timeout.terminal_status == "timed_out"
    timeout_trace = L1TraceService(L1TraceStore(tmp_path / "timeout.sqlite")); timeout_state = bridge.reduce_and_trace(timeout_trace, "trace-timeout", state, run_id="run-timeout", next_state_id="state-timeout")
    assert timeout_state.diagnosis["runtime_terminal_status"] == "timed_out"
    assert timeout_trace.store.read("trace-timeout")[0].facts["terminal_status"] == "timed_out"
    runtime.describe = lambda run_id: {"run": {"status": "failed", "terminal_reason": "lost", "task_spec": {"labels": {"l1_goal_id": "goal-1"}}}, "stages": [{"stage_key": "route", "attempts": [{"attempt_id": "attempt-lost", "status": "lost", "metrics": [], "artifacts": []}]}]}
    lost = bridge.observation("run-lost")
    assert lost.attempt_id == "attempt-lost" and lost.terminal_status == "lost"
    lost_trace = L1TraceService(L1TraceStore(tmp_path / "lost.sqlite")); lost_state = bridge.reduce_and_trace(lost_trace, "trace-lost", state, run_id="run-lost", next_state_id="state-lost")
    assert lost_state.diagnosis["runtime_terminal_status"] == "lost"
    assert lost_trace.store.read("trace-lost")[0].facts["terminal_status"] == "lost"


class _FixtureFactory:
    capability = "eda.rtl_to_gds"
    def validate_task(self, task): task.validate()
    def reconfigure(self, task, values): return task


def test_runtime_bridge_real_workflow_runtime_smoke(tmp_path):
    fixture = Path(__file__).parent / "fixtures" / "echo_adapter.py"
    manifest = PluginManifest("fixture", "1.0.0", (sys.executable, str(fixture)), ("eda.rtl_to_gds",), (platform.machine(),),
                              {"type": "object"}, {"type": "object"}, ({"kind": "report", "required": True},), 10)
    runtime = WorkflowRuntime(RuntimeStore(tmp_path / "runtime.sqlite"), PluginRegistry([manifest]), workspace_root=tmp_path / "work", adapter=ProcessAdapter(ProcessGuardian(poll_interval=0.01, terminate_grace=0.1)))
    task = TaskSpec("base-task", "p1", "top", plugin_id="fixture", inputs={"message": "l1 smoke"}, expected_artifacts=("report",), timeout_seconds=10)
    bridge = L1RuntimeBridge(runtime, task, _FixtureFactory())
    goal = DesignGoal("goal-1", "p1", "top", "platform-1", "pdk-1", "toolchain-1", EvidencePointer("artifact:rtl", "a" * 64), GoalPreference.BALANCED, (QoRConstraint("setup_wns_ns", ">=", 0),), ("route",), ("density",), AgentBudget(2, 2, 60))
    state = DesignState("state-1", "goal-1", 0, "running", None, {}, AgentBudget(2, 2, 60))
    receipt = bridge.submit(goal, state, SemanticToolCall("call-smoke", "goal-1", "state-1", ToolName.RUN_FULL_FLOW, {}, "planner"))
    runtime.execute_once(receipt.result["run_id"])
    artifact_id = runtime.describe(receipt.result["run_id"])["stages"][0]["attempts"][0]["artifacts"][0]["artifact_id"]
    excerpt = bridge.execute(goal, state, SemanticToolCall("call-excerpt", "goal-1", "state-1", ToolName.QUERY_ARTIFACT_EXCERPT, {"run_id": receipt.result["run_id"], "artifact_id": artifact_id, "max_bytes": 64}, "planner"))
    assert "bytes" in excerpt.result and bridge.observation(receipt.result["run_id"]).terminal_status == "succeeded"


def test_durable_loop_real_runtime_submit_execute_observe(tmp_path):
    fixture = Path(__file__).parent / "fixtures" / "echo_adapter.py"
    manifest = PluginManifest("fixture", "1.0.0", (sys.executable, str(fixture)), ("eda.rtl_to_gds",), (platform.machine(),), {"type": "object"}, {"type": "object"}, ({"kind": "report", "required": True},), 10)
    runtime = WorkflowRuntime(RuntimeStore(tmp_path / "loop-runtime.sqlite"), PluginRegistry([manifest]), workspace_root=tmp_path / "loop-work", adapter=ProcessAdapter(ProcessGuardian(poll_interval=0.01, terminate_grace=0.1)))
    bridge = L1RuntimeBridge(runtime, TaskSpec("loop-base", "p1", "top", plugin_id="fixture", inputs={"message":"loop"}, expected_artifacts=("report",), timeout_seconds=10), _FixtureFactory())
    policy = TrustedPolicyIdentity("policy-1","v1","platform",EvidencePointer("artifact:policy","d"*64))
    goal = DesignGoal("goal-1","p1","top","platform-1","pdk-1","toolchain-1",EvidencePointer("artifact:rtl","a"*64),GoalPreference.BALANCED,(QoRConstraint("setup_wns_ns",">=",0),),("route",),("density",),AgentBudget(2,2,60),allowed_tools=(ToolName.RUN_FULL_FLOW,),labels={"l1_policy_id":"policy-1","l1_policy_version":"v1","l1_policy_issuer":"platform","l1_policy_provenance":"artifact:policy","l1_policy_provenance_sha256":"d"*64})
    state = DesignState("state-1","goal-1",0,"running",None,{},AgentBudget(2,2,60))
    trace=L1TraceService(L1TraceStore(tmp_path/"loop-trace.sqlite")); trace.record_goal("trace-loop",goal)
    loop=L1DurableLoop(L1LoopStore(tmp_path/"loop.sqlite"),bridge,trace)
    plan=loop.plan_validate_execute("trace-loop",goal,state,SemanticToolCall("call-loop","goal-1","state-1",ToolName.RUN_FULL_FLOW,{},"planner"),policy,planner_summary="bounded flow")
    runtime.execute_once(plan["run_id"])
    successor=loop.observe("trace-loop",state,plan["plan_id"],next_state_id="state-2")
    assert successor.diagnosis["runtime_run_id"] == plan["run_id"]
