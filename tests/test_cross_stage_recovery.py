from __future__ import annotations

from pathlib import Path

import pytest

from openroad_platform_analysis import diagnose_terminal_failure
from openroad_platform_contracts import (
    ConvergenceState, EvidencePointer, PlannerPhase, PlannerState,
    RecoveryAction, RecoveryBudget, RecoveryClass, RecoveryDecision,
    RollbackCheckpoint, RTLCandidate, RuntimeFailureClass,
)
from openroad_platform_scheduler import (
    L1ControlStateStore, PDAgentControlStateMachine,
    plan_rtl_checkpoint_restore,
    select_rtl_checkpoint_candidate,
)


TARGET_SHA = "a" * 64
RUN_EVIDENCE = EvidencePointer("run:failed", "b" * 64)
TARGET_EVIDENCE = EvidencePointer(
    f"artifact:rtl-candidate:{TARGET_SHA}", TARGET_SHA)


def _failure_view():
    return {
        "run": {
            "run_id": "run-failed", "status": "failed",
            "task_spec": {"plugin_id": "orfs"},
        },
        "stages": [{"attempts": [{
            "attempt_id": "attempt-failed", "status": "failed",
            "failure": {"category": "orfs_failure", "message": "synth failed"},
            "artifacts": [{
                "artifact_id": "log-failed", "sha256": "c" * 64,
                "metadata": {},
            }],
        }]}],
    }


def _decision():
    return RecoveryDecision(
        "decision-1", "planner-1", "diagnosis-1", "assessment-1",
        RecoveryAction.REQUEST_TYPED_FIX, "evidence_backed_blocker_requires_bounded_fix",
        (RUN_EVIDENCE,), recovery_class=RecoveryClass.MESO,
    )


def _checkpoint():
    return RollbackCheckpoint(
        "checkpoint-1", "goal-1", "planner-clean", 1, "finish", 0,
        "run-clean-verify", "d" * 64, (TARGET_EVIDENCE,),
    )


def _lineage():
    target = RTLCandidate(
        "candidate-clean", "spec-1", "verify-1",
        f"artifact:rtl-candidate:{TARGET_SHA}", "rtlscout-v2",
    )
    failed = RTLCandidate(
        "candidate-failed", "spec-1", "verify-1",
        f"artifact:rtl-candidate:{'e' * 64}", "fault-injection-v1",
        (target.candidate_id,),
    )
    return {
        "candidates": [target.to_dict(), failed.to_dict()],
        "checks": [
            {
                "candidate_id": target.candidate_id,
                "check_kind": "compile_lint", "status": "passed",
                "evidence_ref": "artifact:runtime:verify", "evidence_sha256": "f" * 64,
                "detail": {"run_id": "run-clean-verify"},
            },
            {
                "candidate_id": target.candidate_id,
                "check_kind": "simulation", "status": "passed",
                "evidence_ref": "artifact:runtime:simulation",
                "evidence_sha256": "1" * 64,
                "detail": {"run_id": "run-clean-sim"},
            },
        ],
    }


def test_terminal_failure_is_a_four_domain_unknown_not_fake_qor():
    report, failure_class = diagnose_terminal_failure(_failure_view())
    assert failure_class is RuntimeFailureClass.UNKNOWN
    assert report.blockers == ("backend_execution_failed",)
    assert len(report.analyses) == 4
    assert all(not item.facts and item.completeness.value == "unavailable"
               for item in report.analyses)
    assert any(item.ref == "artifact:runtime-log-failed"
               for item in report.evidence)
    machine = PDAgentControlStateMachine()
    state = machine.initialize("goal-failed", ("finish",), report.evidence)
    state = machine.runtime_submitted(
        state, run_id="run-failed", evidence=report.evidence)
    state = machine.runtime_terminal(
        state, terminal_status="failed", evidence=report.evidence)
    state, _analyzer, debugger = machine.analysis_completed(state, report)
    assert state.phase is PlannerPhase.DEBUGGING
    assert debugger is not None and debugger.basis_fact_ids == ()


def test_restore_plan_selects_only_verified_direct_ancestor():
    lineage = _lineage()
    plan = plan_rtl_checkpoint_restore(
        _decision(), _checkpoint(), lineage,
        failed_candidate_id="candidate-failed",
        target_candidate_id="candidate-clean",
    )
    selected = select_rtl_checkpoint_candidate(plan, lineage)
    assert selected.candidate_id == "candidate-clean"
    assert plan.target_rtl_sha256 == TARGET_SHA
    assert not hasattr(plan, "command") and not hasattr(plan, "source")

    lineage["candidates"][1]["parent_candidate_ids"] = []
    with pytest.raises(ValueError, match="direct candidate ancestor"):
        plan_rtl_checkpoint_restore(
            _decision(), _checkpoint(), lineage,
            failed_candidate_id="candidate-failed",
            target_candidate_id="candidate-clean",
        )


def test_restore_plan_is_durable_and_binds_existing_decision(tmp_path: Path):
    store = L1ControlStateStore(tmp_path / "control.sqlite")
    planner = PlannerState(
        "planner-1", "goal-1", 0, PlannerPhase.REVIEWING, ("finish",), 0,
        ConvergenceState.UNKNOWN, RecoveryBudget(), (RUN_EVIDENCE,),
        convergence_assessment_id="assessment-1", last_run_id="run-failed",
        diagnosis_report_id="diagnosis-1",
    )
    store.append_planner(planner)
    decision = _decision()
    store.append_recovery_decision(decision)
    plan = plan_rtl_checkpoint_restore(
        decision, _checkpoint(), _lineage(),
        failed_candidate_id="candidate-failed",
        target_candidate_id="candidate-clean",
    )
    store.append_rtl_restore_plan(plan)
    assert store.get_rtl_restore_plan(plan.plan_id) == plan
