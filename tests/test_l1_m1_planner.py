from __future__ import annotations

import pytest

from apps.l1_workbench.m1_planner import M1EvidencePlanner
from openroad_platform_contracts.agent_control import AgentBudget, DesignGoal, DesignState, GoalPreference, QoRConstraint
from openroad_platform_contracts.learning import EvidencePointer


def _goal() -> DesignGoal:
    return DesignGoal("goal-1", "tutorial_mux", "mux_2to1", "nangate45", "nangate45", "orfs-2d-baseline",
        EvidencePointer("artifact:rtl", "a" * 64), GoalPreference.PERFORMANCE,
        (QoRConstraint("setup_wns_ns", ">=", 0), QoRConstraint("drc_errors", "<=", 0),
         QoRConstraint("area_baseline_ratio", "<=", 1.03)), ("finish",),
        ("place_density",), AgentBudget(3, 4, 7200))


def _state(metrics: dict[str, float], run: str) -> DesignState:
    return DesignState("state-" + run, "goal-1", 1, "observed", "state-0", metrics, AgentBudget(2, 4, 7200),
        diagnosis={"runtime_run_id": run, "runtime_terminal_status": "succeeded"})


def test_m1_planner_proposal_is_based_on_canonical_baseline_and_registered_parameter() -> None:
    proposal = M1EvidencePlanner.propose(_goal(), _state({"setup_wns_ns": -0.12, "area_um2": 101.5, "drc_errors": 0}, "run-baseline"))
    assert proposal.values == {"place_density": 0.50}
    assert "-0.12" in proposal.summary and "101.5" in proposal.summary
    assert proposal.hypothesis["baseline_runtime_run_id"] == "run-baseline"


def test_m1_planner_does_not_claim_candidate_success_without_measured_constraints() -> None:
    baseline = _state({"setup_wns_ns": 0.1, "area_um2": 100.0, "drc_errors": 0}, "run-baseline")
    worse = _state({"setup_wns_ns": 0.0, "area_um2": 101.0, "drc_errors": 0}, "run-candidate")
    decision, summary, facts = M1EvidencePlanner.decide(baseline, worse)
    assert decision == "stop" and facts["reason"] == "no_measured_improvement"
    assert "does not improve" in summary
    violating = _state({"setup_wns_ns": 0.2, "area_um2": 104.0, "drc_errors": 0}, "run-bad")
    assert M1EvidencePlanner.decide(baseline, violating)[2]["reason"] == "candidate_constraint_violation"


def test_m1_planner_requires_complete_real_baseline_observation() -> None:
    with pytest.raises(ValueError, match="baseline metrics"):
        M1EvidencePlanner.propose(_goal(), _state({"setup_wns_ns": 0.1}, "run-baseline"))


def test_m1_planner_records_stop_for_failed_or_metricless_candidate() -> None:
    baseline = _state({"setup_wns_ns": 0.1, "area_um2": 100.0, "drc_errors": 0}, "run-baseline")
    failed = DesignState("state-failed", "goal-1", 2, "failed", "state-run-baseline", {},
                         AgentBudget(1, 4, 7200),
                         diagnosis={"runtime_run_id": "run-failed", "runtime_terminal_status": "failed"})
    decision, summary, facts = M1EvidencePlanner.decide(baseline, failed)
    assert decision == "stop"
    assert facts["reason"] == "candidate_not_observable"
    assert "preserve failure evidence" in summary
