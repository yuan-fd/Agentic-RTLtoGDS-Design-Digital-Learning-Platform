from types import SimpleNamespace
import pytest

from openroad_platform_contracts.agent_control import AgentBudget, DesignGoal, DesignState, GoalPreference, QoRConstraint
from openroad_platform_contracts.l2_optimization import OptimizationRequest
from openroad_platform_contracts.learning import EvidencePointer
from openroad_platform_contracts.platform import PluginManifest, TaskSpec
from openroad_platform_contracts.product_surface import DEFAULT_PRODUCT_SURFACE
from openroad_platform_scheduler.l2_handoff import OptimizationHandoffService


def _goal_state():
    goal = DesignGoal("goal-1", "project-1", "design-1", "platform-1", "pdk-1", "toolchain-1",
        EvidencePointer("artifact:rtl", "a" * 64), GoalPreference.BALANCED,
        (QoRConstraint("wns", ">=", 0),), ("finish",), ("density",), AgentBudget(4, 2, 60))
    state = DesignState("state-1", goal.goal_id, 1, "completed", "finish", {"wns": 0.0},
        AgentBudget(3, 2, 60), evidence=(EvidencePointer("run:verified", "b" * 64),))
    return goal, state


def _request():
    return OptimizationRequest("request-1", "trace-1", "goal-1", "state-1", "a2-orfo",
        "optimizer.l2.a2-orfo-feedback", "minimize area subject to timing", EvidencePointer("artifact:protocol", "c" * 64),
        EvidencePointer("artifact:search-space", "d" * 64), "fixed-seed-v1", AgentBudget(4, 2, 60))


def _manifest(plugin_id="a2-orfo", capabilities=("optimizer.l2.a2-orfo-feedback",)):
    return PluginManifest(plugin_id, "2025.1", ("adapter",), capabilities, ("x86_64",),
        {"type": "object"}, {"type": "object"}, (), 60)


def _builder(request, goal, state):
    return TaskSpec("l2-task", goal.project_id, goal.design_id, plugin_id=request.plugin_id,
                    inputs={"mode": "native"}, timeout_seconds=60)


def test_handoff_authorizes_external_product_plugin_and_binds_correlation():
    goal, state = _goal_state(); request = _request()
    task = OptimizationHandoffService(DEFAULT_PRODUCT_SURFACE, _builder).task_for(request, goal, state, _manifest())
    assert task.labels["l1_trace_id"] == "trace-1"
    assert task.labels["l2_protocol_sha256"] == "c" * 64


def test_handoff_rejects_unverified_state_foreign_plugin_and_foreign_task():
    goal, state = _goal_state(); request = _request()
    service = OptimizationHandoffService(DEFAULT_PRODUCT_SURFACE, _builder)
    with pytest.raises(ValueError, match="terminal"):
        service.task_for(request, goal, DesignState("state-1", goal.goal_id, 0, "running", None, {}, AgentBudget(4,2,60)), _manifest())
    with pytest.raises(ValueError, match="terminal"):
        service.task_for(request, goal, DesignState("state-1", goal.goal_id, 1, "observed", "finish", {"wns": 0.0},
                                                    AgentBudget(3,2,60), evidence=(EvidencePointer("run:verified", "b" * 64),)), _manifest())
    with pytest.raises(PermissionError):
        service.task_for(request, goal, state, _manifest("local-bo"))
    foreign = OptimizationHandoffService(DEFAULT_PRODUCT_SURFACE,
        lambda r, g, s: TaskSpec("foreign", "other-project", g.design_id, plugin_id=r.plugin_id, inputs={}, timeout_seconds=60))
    with pytest.raises(ValueError, match="Goal identity"):
        foreign.task_for(request, goal, state, _manifest())


def test_handoff_rejects_non_product_capability_from_an_admitted_manifest():
    goal, state = _goal_state()
    request = OptimizationRequest("request-1", "trace-1", "goal-1", "state-1", "a2-orfo",
        "unapproved.l2.action", "minimize area subject to timing", EvidencePointer("artifact:protocol", "c" * 64),
        EvidencePointer("artifact:search-space", "d" * 64), "fixed-seed-v1", AgentBudget(4, 2, 60))
    with pytest.raises(PermissionError, match="approved product capability"):
        OptimizationHandoffService(DEFAULT_PRODUCT_SURFACE, _builder).task_for(
            request, goal, state, _manifest(capabilities=("optimizer.l2.a2-orfo-feedback", "unapproved.l2.action")))


def test_handoff_only_submits_through_runtime():
    goal, state = _goal_state(); request = _request()
    class Runtime:
        def submit(self, task, *, capability):
            self.task, self.capability = task, capability
            return SimpleNamespace(run_id="run-1")
    runtime = Runtime()
    run = OptimizationHandoffService(DEFAULT_PRODUCT_SURFACE, _builder).submit(runtime, request, goal, state, _manifest())
    assert run.run_id == "run-1" and runtime.capability == "optimizer.l2.a2-orfo-feedback"
