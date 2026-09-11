from __future__ import annotations

from dataclasses import replace

import pytest

from openroad_platform_analysis import classify_convergence, diagnose_runtime
from openroad_platform_contracts import (
    AnalysisTarget, ConvergencePolicy, EvidencePointer, L2HandoffAuthorization,
    MetricTrajectory, MetricTrajectoryPoint, ObjectiveDirection, RecoveryAction,
    RecoveryBudget, RollbackCheckpoint, RuntimeFailureClass,
)
from openroad_platform_scheduler import (
    L1ControlStateStore, PDAgentControlStateMachine, decide_recovery,
)


EVIDENCE = (EvidencePointer("artifact:metric", "a" * 64),)
PROTOCOL = "b" * 64


def _report(*, wns=0.1):
    return diagnose_runtime({
        "run": {"run_id": "run-2", "status": "succeeded"},
        "stages": [{"stage_key": "finish", "attempts": [{
            "attempt_id": "attempt-2", "status": "succeeded", "metrics": [],
            "artifacts": [{"artifact_id": "official-2", "sha256": "a" * 64,
                           "metadata": {"runtime_authority": "protected_evaluator",
                                        "official_qor": True,
                                        "canonical_metrics": {
                                            "setup_wns_ns": wns,
                                            "drc_errors": 0, "power_W": 0.1}}}],
        }]}],
    }, targets=(AnalysisTarget("setup_wns_ns", ">=", 0, "ns", EVIDENCE),))


def _assessment(values):
    trajectory = MetricTrajectory(
        "trajectory-1", "setup_wns_ns", "ns", ObjectiveDirection.MAXIMIZE,
        PROTOCOL, tuple(MetricTrajectoryPoint(
            f"point-{index}", index, f"run-{index}", f"attempt-{index}",
            "finish", "setup_wns_ns", "ns", "succeeded", PROTOCOL,
            "protected_evaluator", EVIDENCE, value=value)
            for index, value in enumerate(values)), EVIDENCE)
    return classify_convergence(
        trajectory, ConvergencePolicy("policy-1", 0.01, 0, 3, 3, 2))


def _state(report, assessment, *, budget=RecoveryBudget()):
    machine = PDAgentControlStateMachine()
    state = machine.initialize("goal-1", ("finish",), EVIDENCE,
                               recovery_budget=budget)
    state = machine.runtime_submitted(state, run_id="run-2", evidence=EVIDENCE)
    state = machine.runtime_terminal(state, terminal_status="succeeded",
                                     evidence=EVIDENCE)
    state, _analyzer, _debugger = machine.analysis_completed(state, report)
    return machine.record_convergence(state, assessment)


def _rollback(state):
    return RollbackCheckpoint(
        "checkpoint-clean", state.goal_id, "planner-old", 1, "finish", 0,
        "run-clean", PROTOCOL, EVIDENCE)


def _authorization():
    return L2HandoffAuthorization(
        "l2-auth-1", "trace-1", "goal-1", "design-state-1", "reflection-1",
        "run-baseline", "run-candidate", EVIDENCE)


def test_diverging_trajectory_selects_latest_clean_rollback_and_is_durable(tmp_path):
    report = _report()
    assessment = _assessment((0.3, 0.1, -0.2))
    state = _state(report, assessment)
    checkpoint = _rollback(state)
    decision = decide_recovery(
        state, report, assessment, rollback_checkpoints=(checkpoint,))
    assert decision.action is RecoveryAction.ROLLBACK
    assert decision.rollback_checkpoint_id == checkpoint.checkpoint_id

    store = L1ControlStateStore(tmp_path / "control.sqlite")
    # The decision store requires its exact source PlannerState to exist.
    initial = replace(state, parent_state_id=None, revision=0)
    store.append_planner(initial)
    bound = replace(decision, planner_state_id=initial.planner_state_id)
    store.append_recovery_decision(bound)
    assert store.get_recovery_decision(bound.decision_id) == bound


def test_blocker_requests_only_typed_meso_fix():
    report = _report(wns=-0.2)
    assessment = _assessment((-0.3, -0.2))
    state = _state(report, assessment)
    decision = decide_recovery(state, report, assessment)
    assert decision.action is RecoveryAction.REQUEST_TYPED_FIX
    assert decision.recovery_class.value == "meso"
    assert not decision.l2_plugin_id and not decision.rollback_checkpoint_id


def test_stalled_requires_authorization_then_targets_a2_orfo():
    report = _report()
    assessment = _assessment((0.1, 0.101, 0.099))
    state = _state(report, assessment)
    denied = decide_recovery(state, report, assessment)
    assert denied.action is RecoveryAction.STOP
    assert denied.reason_code == "stalled_but_l2_authorization_missing"
    allowed = decide_recovery(
        state, report, assessment, l2_authorization=_authorization())
    assert allowed.action is RecoveryAction.ESCALATE_L2
    assert allowed.l2_plugin_id == "a2-orfo"
    assert allowed.l2_capability == "optimizer.l2.a2-orfo-feedback"


def test_transient_failure_can_retry_but_other_failure_cannot_hide_blocker():
    report = _report(wns=-0.2)
    assessment = _assessment((-0.3, -0.2))
    state = _state(report, assessment)
    retry = decide_recovery(
        state, report, assessment,
        failure_class=RuntimeFailureClass.TRANSIENT_INFRASTRUCTURE)
    assert retry.action is RecoveryAction.RETRY
    nontransient = decide_recovery(
        state, report, assessment,
        failure_class=RuntimeFailureClass.DESIGN)
    assert nontransient.action is RecoveryAction.REQUEST_TYPED_FIX


def test_exhausted_budget_stops_and_foreign_checkpoint_is_rejected():
    report = _report(wns=-0.2)
    assessment = _assessment((-0.3, -0.2))
    state = _state(report, assessment, budget=RecoveryBudget(0, 0, 0))
    assert decide_recovery(state, report, assessment).action is RecoveryAction.STOP
    with pytest.raises(ValueError, match="another goal"):
        decide_recovery(
            state, report, assessment,
            rollback_checkpoints=(replace(_rollback(state), goal_id="goal-2"),))
