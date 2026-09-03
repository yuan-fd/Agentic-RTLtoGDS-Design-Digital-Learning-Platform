from __future__ import annotations

from types import SimpleNamespace

import pytest

from openroad_platform_contracts import (
    AgentBudget, DesignGoal, DesignState, EvidencePointer, GoalPreference,
    QoRConstraint, SemanticToolCall, ToolName,
)
from openroad_platform_execution import ORFSRTLToGDSFactory, build_orfs_task
from openroad_platform_scheduler import L1ORFSToolService


class FakeRuntime:
    def __init__(self):
        self.submissions = []

    def submit(self, task, *, capability):
        self.submissions.append((task, capability))
        return SimpleNamespace(run_id="run-accepted")

    def describe(self, run_id):
        return {"run_id": run_id, "status": "succeeded", "metrics": {"setup_wns_ns": 0.1}}


def _goal():
    return DesignGoal(
        goal_id="goal-1", project_id="p1", design_id="top", platform="nangate45",
        pdk_id="nangate45", toolchain_id="orfs-pinned",
        rtl_artifact=EvidencePointer("artifact:rtl", "a" * 64),
        preference=GoalPreference.BALANCED,
        hard_constraints=(QoRConstraint("setup_wns_ns", ">=", 0.0),
                          QoRConstraint("drc_errors", "<=", 0.0)),
        allowed_stages=("synth", "floorplan", "place", "cts", "route", "finish"),
        allowed_parameters=("core_utilization_pct",),
        budget=AgentBudget(2, 4, 3600, 1),
    )


def _state():
    return DesignState("state-1", "goal-1", 0, "new", None, {},
                       AgentBudget(2, 4, 3600, 1))


def test_l1_service_creates_validated_task_submits_only_through_runtime(tmp_path):
    rtl = tmp_path / "top.v"
    rtl.write_text("module top(input a, output y); assign y=a; endmodule\n")
    base = build_orfs_task(rtl, project_id="p1", design_id="top", top="top")
    runtime = FakeRuntime(); service = L1ORFSToolService(runtime, base, ORFSRTLToGDSFactory())
    goal = _goal(); initial = _state()

    created = service.execute(goal, initial, SemanticToolCall(
        "call-1", goal.goal_id, initial.state_id, ToolName.CREATE_EXPERIMENT,
        {"name": "baseline", "or_seed": 101}, "agent"))
    assert created.status == "completed"
    experiment_id = created.result["experiment_id"]
    configured_state = service.state(created.next_state_id)
    configured = service.execute(goal, configured_state, SemanticToolCall(
        "call-2", goal.goal_id, configured_state.state_id, ToolName.SET_FLOW_PARAMS,
        {"experiment_id": experiment_id, "values": {"core_utilization_pct": 20}}, "agent"))
    run_state = service.state(configured.next_state_id)
    submitted = service.execute(goal, run_state, SemanticToolCall(
        "call-3", goal.goal_id, run_state.state_id, ToolName.RUN_STAGE,
        {"experiment_id": experiment_id, "stage": "finish"}, "agent"))
    assert submitted.status == "accepted"
    assert runtime.submissions[0][1] == "eda.rtl_to_gds"
    assert runtime.submissions[0][0].parameters["core_utilization_pct"] == 20
    assert service.state(submitted.next_state_id).remaining_budget.max_eda_runs == 1

    observed = service.observe(service.state(submitted.next_state_id), run_id="run-accepted",
                               metrics={"setup_wns_ns": 0.1, "drc_errors": 0.0},
                               evidence=EvidencePointer("run:run-accepted", "b" * 64),
                               completed_stage="finish")
    assert observed.metrics["setup_wns_ns"] == 0.1


def test_l1_service_query_returns_hashed_runtime_view(tmp_path):
    rtl = tmp_path / "top.v"; rtl.write_text("module top; endmodule\n")
    service = L1ORFSToolService(
        FakeRuntime(), build_orfs_task(rtl, project_id="p1", design_id="top"),
        ORFSRTLToGDSFactory(),
    )
    goal = _goal(); state = _state()
    receipt = service.execute(goal, state, SemanticToolCall(
        "call-4", goal.goal_id, state.state_id, ToolName.QUERY_TIMING,
        {"run_id": "run-accepted", "limit": 4}, "agent"))
    assert receipt.status == "completed"
    assert receipt.evidence[0].ref == "run:run-accepted"


def test_l1_service_rejects_a_capability_mismatch_at_the_factory_boundary(tmp_path):
    rtl = tmp_path / "top.v"; rtl.write_text("module top; endmodule\n")
    with pytest.raises(ValueError, match="must match"):
        L1ORFSToolService(
            FakeRuntime(), build_orfs_task(rtl, project_id="p1", design_id="top"),
            ORFSRTLToGDSFactory(), capability="eda.somewhere-else",
        )
