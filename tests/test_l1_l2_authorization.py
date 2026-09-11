from datetime import datetime, timezone

import pytest

from openroad_platform_contracts.agent_control import AgentBudget, DesignGoal, DesignState, GoalPreference, QoRConstraint
from openroad_platform_contracts.l1_observation import RuntimeObservation
from openroad_platform_contracts.learning import EvidencePointer
from openroad_platform_contracts.l2_optimization import OptimizationRequest
from openroad_platform_contracts.platform import PluginManifest, TaskSpec
from openroad_platform_contracts.product_surface import DEFAULT_PRODUCT_SURFACE
from openroad_platform_scheduler.l1_l2_authorization import L1L2AuthorizationService
from openroad_platform_scheduler.l1_state_reducer import L1StateReducer
from openroad_platform_scheduler.l1_trace_service import L1TraceService
from openroad_platform_scheduler.l1_trace_store import L1TraceStore
from openroad_platform_scheduler.l2_handoff import OptimizationHandoffService
from openroad_platform_scheduler.l2_handoff_store import L2HandoffStore
from openroad_platform_scheduler.pipeline_checkpoint import PipelineCheckpointStore


def _goal():
    return DesignGoal("goal-1", "project-1", "design-1", "platform-1", "pdk-1", "toolchain-1",
        EvidencePointer("artifact:rtl", "a" * 64), GoalPreference.PERFORMANCE,
        (QoRConstraint("setup_wns_ns", ">=", 0),), ("finish",), ("place_density",), AgentBudget(3, 1, 60))


def _observe(trace, before, state_id, run):
    observation = RuntimeObservation(
        run_id=run, attempt_id=f"attempt-{run}", terminal_status="succeeded", metrics={"setup_wns_ns": .1},
        evidence=(EvidencePointer(f"run:{run}", "b" * 64),), completed_stage="finish")
    after = L1StateReducer.apply(before, observation, next_state_id=state_id, consume_eda_run=True)
    trace.record_observation("trace-1", before, after, observation, consume_eda_run=True)
    return after


def _manifest():
    return PluginManifest("a2-orfo", "2026.06.23", ("adapter",), ("optimizer.l2.a2-orfo-feedback",), ("x86_64",),
        {"type": "object"}, {"type": "object"}, (), 60)


def _request(state):
    return OptimizationRequest("request-1", "trace-1", "goal-1", state.state_id, "a2-orfo", "optimizer.l2.a2-orfo-feedback",
        "maximize setup WNS", EvidencePointer("artifact:protocol", "c" * 64),
        EvidencePointer("artifact:domain", "d" * 64), "fixed-seed-v1", AgentBudget(2, 1, 60))


def test_only_explicit_escalation_with_two_runtime_facts_can_authorize(tmp_path):
    trace = L1TraceService(L1TraceStore(tmp_path / "trace.sqlite")); goal = _goal(); trace.record_goal("trace-1", goal)
    initial = DesignState("state-0", goal.goal_id, 0, "running", None, {}, AgentBudget(3, 1, 60), evidence=(goal.rtl_artifact,))
    baseline = _observe(trace, initial, "state-1", "run-baseline")
    candidate = _observe(trace, baseline, "state-2", "run-candidate")
    with pytest.raises(ValueError, match="explicit durable escalate"):
        L1L2AuthorizationService(trace).authorize("trace-1", goal, candidate)
    reflection = trace.record_reflection("trace-1", candidate, summary="Measured candidates justify a bounded external search.",
        decision="escalate", evidence=candidate.evidence, hypotheses={"reason": "bounded search"},
        basis_event_ids=(trace.store.read("trace-1")[-1].event_id,))
    auth = L1L2AuthorizationService(trace).authorize("trace-1", goal, candidate)
    assert auth.reflection_event_id == reflection.event_id
    assert trace.store.read("trace-1")[-1].kind.value == "l2_handoff_authorized"
    assert L1L2AuthorizationService(trace).authorize("trace-1", goal, candidate) == auth
    assert len([e for e in trace.store.read("trace-1") if e.kind.value == "l2_handoff_authorized"]) == 1

    class Runtime:
        count = 0
        def submit(self, task, *, capability): self.count += 1; return type("Run", (), {"run_id":"run-l2"})()
    runtime=Runtime()
    one_shot=OptimizationHandoffService(DEFAULT_PRODUCT_SURFACE,
        lambda request, bound_goal, state: TaskSpec("task-2", bound_goal.project_id, bound_goal.design_id, plugin_id=request.plugin_id, inputs={"mode":"native_agent"}, timeout_seconds=60),
        trace_store=trace.store, consumption_store=L2HandoffStore(tmp_path/"handoff.sqlite"))
    assert one_shot.submit_authorized(runtime,_request(candidate),goal,candidate,auth,_manifest()).run_id == "run-l2"
    assert one_shot.submit_authorized(runtime,_request(candidate),goal,candidate,auth,_manifest()).run_id == "run-l2"
    assert runtime.count == 1

    # A claimant may die before binding. The deterministic controller subject
    # recovers that gap and repeated calls return the same durable pipeline.
    controller_store = L2HandoffStore(tmp_path / "controller-handoff.sqlite")
    assert controller_store.claim_target(auth.authorization_id) is None
    checkpoints = PipelineCheckpointStore(tmp_path / "controllers.sqlite")
    controller_handoff = OptimizationHandoffService(
        DEFAULT_PRODUCT_SURFACE, None, trace_store=trace.store,
        consumption_store=controller_store,
    )
    first = controller_handoff.create_authorized_controller(
        checkpoints, _request(candidate), goal, candidate, auth, _manifest(),
        pipeline_kind="a2-orfo-campaign-v1",
        initial_state={"status": "authorized", "request": _request(candidate).to_dict(),
                       "authorization": auth.to_dict()},
    )
    second = controller_handoff.create_authorized_controller(
        checkpoints, _request(candidate), goal, candidate, auth, _manifest(),
        pipeline_kind="a2-orfo-campaign-v1",
        initial_state={"status": "authorized", "request": _request(candidate).to_dict(),
                       "authorization": auth.to_dict()},
    )
    assert first["pipeline_id"] == second["pipeline_id"]
    assert controller_store.claim_target(auth.authorization_id) == (
        "pipeline", first["pipeline_id"])


def test_handoff_rejects_forged_or_missing_durable_authorization(tmp_path):
    goal = _goal(); state = _observed = L1StateReducer.apply(
        DesignState("state-0", goal.goal_id, 0, "running", None, {}, AgentBudget(3, 1, 60), evidence=(goal.rtl_artifact,)),
        RuntimeObservation("run-1", "attempt-run-1", "finish", "succeeded", {"setup_wns_ns": .1}, (EvidencePointer("run:run-1", "b" * 64),)), next_state_id="state-1", consume_eda_run=True)
    from openroad_platform_contracts.l2_optimization import L2HandoffAuthorization
    forged = L2HandoffAuthorization("l2-auth-forged", "trace-1", goal.goal_id, state.state_id, "reflection-1", "run-0", "run-1", state.evidence)
    service = OptimizationHandoffService(DEFAULT_PRODUCT_SURFACE,
        lambda r, g, s: TaskSpec("task-1", g.project_id, g.design_id, plugin_id=r.plugin_id, inputs={}, timeout_seconds=60),
        consumption_store=L2HandoffStore(tmp_path / "forged.sqlite"))
    class Runtime:
        def submit(self, *_args, **_kwargs): raise AssertionError("forged authorization must not reach Runtime")
    with pytest.raises(ValueError, match="durable trace verifier"):
        service.submit_authorized(Runtime(), _request(state), goal, state, forged, _manifest())


def test_observed_state_still_cannot_use_legacy_handoff(tmp_path):
    goal = _goal(); initial = DesignState("state-0", goal.goal_id, 0, "running", None, {}, AgentBudget(3, 1, 60), evidence=(goal.rtl_artifact,))
    state = L1StateReducer.apply(initial, RuntimeObservation("run-1", "attempt-run-1", "finish", "succeeded", {"setup_wns_ns": .1}, (EvidencePointer("run:run-1", "b" * 64),)), next_state_id="state-1", consume_eda_run=True)
    with pytest.raises(ValueError, match="terminal"):
        OptimizationHandoffService(DEFAULT_PRODUCT_SURFACE,
            lambda r, g, s: TaskSpec("task-1", g.project_id, g.design_id, plugin_id=r.plugin_id, inputs={}, timeout_seconds=60)
        ).task_for(_request(state), goal, state, _manifest())
