"""Deterministic L1 recovery policy; proposals only, never execution."""

from __future__ import annotations

from uuid import uuid4

from openroad_platform_contracts import (
    ConvergenceAssessment, ConvergenceState, DiagnosisReport,
    L2HandoffAuthorization, PlannerPhase, PlannerState, RecoveryAction,
    RecoveryClass, RecoveryDecision, RollbackCheckpoint, RuntimeFailureClass,
)


A2_ORFO_PLUGIN_ID = "a2-orfo"
A2_ORFO_CAPABILITY = "optimizer.l2.a2-orfo-feedback"


def decide_recovery(
    state: PlannerState,
    report: DiagnosisReport,
    assessment: ConvergenceAssessment,
    *,
    failure_class: RuntimeFailureClass = RuntimeFailureClass.NONE,
    rollback_checkpoints: tuple[RollbackCheckpoint, ...] = (),
    l2_authorization: L2HandoffAuthorization | None = None,
) -> RecoveryDecision:
    """Return one typed policy decision from persisted facts.

    L2 is proposed only for a stalled trajectory carrying an explicit handoff
    authorization. The handoff service must still verify its durable trace.
    """
    state.validate(); report.validate(); assessment.validate()
    if state.phase not in {PlannerPhase.REVIEWING, PlannerPhase.DEBUGGING}:
        raise ValueError("recovery policy requires reviewed or debugging state")
    if (state.diagnosis_report_id != report.report_id
            or state.convergence_assessment_id != assessment.assessment_id
            or state.convergence is not assessment.state):
        raise ValueError("recovery inputs do not bind the active planner state")
    if not isinstance(failure_class, RuntimeFailureClass):
        raise ValueError("Runtime failure class must be typed")
    for checkpoint in rollback_checkpoints:
        checkpoint.validate()
        if checkpoint.goal_id != state.goal_id:
            raise ValueError("rollback checkpoint belongs to another goal")
    if l2_authorization is not None:
        l2_authorization.validate()
        if l2_authorization.goal_id != state.goal_id:
            raise ValueError("L2 authorization belongs to another goal")

    checkpoint = _latest_rollback(state, rollback_checkpoints)
    if (failure_class is RuntimeFailureClass.TRANSIENT_INFRASTRUCTURE
            and state.recovery_budget.micro_remaining):
        return _decision(state, report, assessment, RecoveryAction.RETRY,
                         "transient_runtime_failure", RecoveryClass.MICRO)
    if assessment.state is ConvergenceState.DIVERGING:
        if checkpoint is not None and state.recovery_budget.macro_remaining:
            return _decision(state, report, assessment, RecoveryAction.ROLLBACK,
                             "material_regression_with_clean_checkpoint",
                             RecoveryClass.MACRO, checkpoint=checkpoint)
        return _decision(state, report, assessment, RecoveryAction.STOP,
                         "diverging_without_rollback_budget_or_checkpoint")
    if report.blockers:
        if state.recovery_budget.meso_remaining:
            return _decision(state, report, assessment,
                             RecoveryAction.REQUEST_TYPED_FIX,
                             "evidence_backed_blocker_requires_bounded_fix",
                             RecoveryClass.MESO)
        if checkpoint is not None and state.recovery_budget.macro_remaining:
            return _decision(state, report, assessment, RecoveryAction.ROLLBACK,
                             "fix_budget_exhausted_with_clean_checkpoint",
                             RecoveryClass.MACRO, checkpoint=checkpoint)
        return _decision(state, report, assessment, RecoveryAction.STOP,
                         "blocker_budget_exhausted")
    if assessment.state is ConvergenceState.STALLED:
        if l2_authorization is None:
            return _decision(state, report, assessment, RecoveryAction.STOP,
                             "stalled_but_l2_authorization_missing")
        return _decision(
            state, report, assessment, RecoveryAction.ESCALATE_L2,
            "stalled_authorized_external_dse", authorization=l2_authorization)
    return _decision(state, report, assessment, RecoveryAction.CONTINUE,
                     "measured_progress_or_more_evidence_required")


def _latest_rollback(state, checkpoints):
    eligible = [item for item in checkpoints
                if item.stage_index <= state.stage_index and item.revision < state.revision]
    return max(eligible, key=lambda item: item.revision) if eligible else None


def _decision(state, report, assessment, action, reason, recovery_class=None,
              *, checkpoint=None, authorization=None):
    evidence = tuple(dict.fromkeys((
        *state.evidence, *report.evidence, *assessment.evidence,
        *(checkpoint.evidence if checkpoint else ()),
        *(authorization.evidence if authorization else ()),
    )))
    result = RecoveryDecision(
        decision_id=f"recovery-{uuid4().hex}",
        planner_state_id=state.planner_state_id,
        diagnosis_report_id=report.report_id,
        convergence_assessment_id=assessment.assessment_id,
        action=action, reason_code=reason, evidence=evidence,
        recovery_class=recovery_class,
        rollback_checkpoint_id=checkpoint.checkpoint_id if checkpoint else None,
        l2_authorization_id=(authorization.authorization_id
                             if authorization else None),
        l2_plugin_id=A2_ORFO_PLUGIN_ID if authorization else None,
        l2_capability=A2_ORFO_CAPABILITY if authorization else None,
    )
    result.validate()
    return result
