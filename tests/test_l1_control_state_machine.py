from __future__ import annotations

import pytest

from openroad_platform_analysis import diagnose_runtime
from openroad_platform_contracts import (
    AnalysisTarget, EvidencePointer, PlannerPhase, RecoveryAction,
    RecoveryBudget, RecoveryClass,
)
from openroad_platform_scheduler import L1ControlStateStore, PDAgentControlStateMachine


def _view(*, setup=-0.2, drc=2):
    return {
        "run": {"run_id": "run-1", "status": "succeeded"},
        "stages": [{"stage_key": "finish", "attempts": [{
            "attempt_id": "attempt-1", "status": "succeeded", "metrics": [],
            "artifacts": [{
                "artifact_id": "official-1", "sha256": "b" * 64,
                "metadata": {"runtime_authority": "protected_evaluator",
                             "official_qor": True, "canonical_metrics": {
                                 "setup_wns_ns": setup, "drc_errors": drc,
                                 "power_W": 0.5}},
            }],
        }]}],
    }


def _report(*, setup=-0.2, drc=2):
    policy = (EvidencePointer("source:analysis-policy", "c" * 64),)
    return diagnose_runtime(_view(setup=setup, drc=drc), targets=(
        AnalysisTarget("setup_wns_ns", ">=", 0, "ns", policy),
        AnalysisTarget("drc_errors", "==", 0, "count", policy),
    ))


def test_pdagent_role_path_is_durable_and_debug_budgeted(tmp_path):
    store = L1ControlStateStore(tmp_path / "control.sqlite")
    machine = PDAgentControlStateMachine()
    source = EvidencePointer("artifact:goal", "a" * 64)
    state = machine.initialize("goal-1", ("route", "finish"), (source,))
    store.append_planner(state)
    submitted = machine.runtime_submitted(
        state, run_id="run-1", evidence=(EvidencePointer("run:run-1", "d" * 64),))
    store.append_planner(submitted)
    analyzing = machine.runtime_terminal(
        submitted, terminal_status="succeeded",
        evidence=(EvidencePointer("artifact:runtime-receipt", "e" * 64),))
    store.append_planner(analyzing)
    debugging, analyzer, debugger = machine.analysis_completed(analyzing, _report())
    assert debugger is not None
    store.append_analyzer(analyzer)
    store.append_planner(debugging)
    store.append_debugger(debugger)
    retry, proposed = machine.propose_debug_action(
        debugging, debugger, action=RecoveryAction.REQUEST_TYPED_FIX,
        recovery_class=RecoveryClass.MESO)
    store.append_debugger(proposed)
    store.append_planner(retry)
    assert retry.phase is PlannerPhase.PLANNING
    assert retry.recovery_budget.meso_remaining == 3
    assert retry.last_run_id is None and retry.diagnosis_report_id is None
    assert store.latest("goal-1") == retry


def test_clean_analysis_advances_stage_then_completes():
    machine = PDAgentControlStateMachine()
    state = machine.initialize(
        "goal-1", ("finish",), (EvidencePointer("artifact:goal", "a" * 64),))
    state = machine.runtime_submitted(
        state, run_id="run-1", evidence=(EvidencePointer("run:run-1", "d" * 64),))
    state = machine.runtime_terminal(
        state, terminal_status="succeeded",
        evidence=(EvidencePointer("artifact:receipt", "e" * 64),))
    reviewing, analyzer, debugger = machine.analysis_completed(
        state, _report(setup=0.1, drc=0))
    assert analyzer.status == "completed" and debugger is None
    assert reviewing.phase is PlannerPhase.REVIEWING
    completed = machine.review_advance(reviewing)
    assert completed.phase is PlannerPhase.COMPLETED
    assert completed.current_stage is None


def test_debugger_cannot_bypass_recovery_class_or_budget():
    machine = PDAgentControlStateMachine()
    initial = machine.initialize(
        "goal-1", ("route",), (EvidencePointer("artifact:goal", "a" * 64),),
        recovery_budget=RecoveryBudget(0, 0, 0))
    submitted = machine.runtime_submitted(
        initial, run_id="run-1", evidence=(EvidencePointer("run:run-1", "d" * 64),))
    analyzing = machine.runtime_terminal(
        submitted, terminal_status="failed",
        evidence=(EvidencePointer("artifact:failure", "e" * 64),))
    debugging, _, debugger = machine.analysis_completed(analyzing, _report())
    assert debugger is not None
    with pytest.raises(ValueError, match="match"):
        machine.propose_debug_action(
            debugging, debugger, action=RecoveryAction.ROLLBACK,
            recovery_class=RecoveryClass.MICRO)
    with pytest.raises(ValueError, match="exhausted"):
        machine.propose_debug_action(
            debugging, debugger, action=RecoveryAction.RETRY,
            recovery_class=RecoveryClass.MICRO)
    escalated, proposed = machine.propose_debug_action(
        debugging, debugger, action=RecoveryAction.ESCALATE_L2)
    assert proposed.proposed_action is RecoveryAction.ESCALATE_L2
    assert escalated.phase is PlannerPhase.ESCALATED
