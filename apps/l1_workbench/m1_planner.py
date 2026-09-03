"""Bounded, evidence-only decision policy for the M1 mux exercise.

This is deliberately not an optimizer.  It converts an observed baseline into
one inspectable, registered-parameter comparison proposal.  The proposal is
useful for proving the L1 control loop; L2 owns multi-candidate optimization.
"""
from __future__ import annotations

from dataclasses import dataclass

from openroad_platform_contracts.agent_control import DesignGoal, DesignState


@dataclass(frozen=True)
class M1CandidateProposal:
    values: dict[str, float]
    summary: str
    hypothesis: dict[str, str]


class M1EvidencePlanner:
    """Make one bounded comparison proposal from canonical Runtime facts."""

    @staticmethod
    def propose(goal: DesignGoal, baseline: DesignState) -> M1CandidateProposal:
        required = {"setup_wns_ns", "area_um2", "drc_errors"}
        missing = sorted(required - set(baseline.metrics))
        if missing:
            raise ValueError("M1 candidate proposal requires baseline metrics: " + ", ".join(missing))
        if baseline.diagnosis.get("runtime_terminal_status") != "succeeded":
            raise ValueError("M1 candidate proposal requires a successful Runtime baseline")
        if "place_density" not in goal.allowed_parameters:
            raise ValueError("M1 profile does not permit the registered place_density parameter")
        wns = baseline.metrics["setup_wns_ns"]
        area = baseline.metrics["area_um2"]
        drc = baseline.metrics["drc_errors"]
        return M1CandidateProposal(
            {"place_density": 0.50},
            "Measured baseline: setup WNS={:.6g} ns, area={:.6g} um², DRC={:.0f}. "
            "The frozen profile permits only registered place_density; submit one bounded "
            "0.50 candidate for comparison. RTL, SDC, PDK, evaluator, and toolchain remain protected."
            .format(wns, area, drc),
            {"reason": "one_registered_parameter_comparison",
             "baseline_runtime_run_id": str(baseline.diagnosis.get("runtime_run_id", ""))},
        )

    @staticmethod
    def decide(baseline: DesignState, candidate: DesignState) -> tuple[str, str, dict[str, str]]:
        required = {"setup_wns_ns", "area_um2", "drc_errors"}
        if candidate.diagnosis.get("runtime_terminal_status") != "succeeded" or required - set(candidate.metrics):
            return "stop", "Candidate has no complete successful canonical QoR observation; preserve failure evidence and stop.", {"reason": "candidate_not_observable"}
        ratio = candidate.metrics["area_um2"] / baseline.metrics["area_um2"]
        if candidate.metrics["drc_errors"] > 0 or ratio > 1.03:
            return "stop", "Candidate violates frozen DRC or area constraints; reject it and stop without an unregistered follow-up change.", {"reason": "candidate_constraint_violation"}
        delta = candidate.metrics["setup_wns_ns"] - baseline.metrics["setup_wns_ns"]
        if delta > 0:
            return "stop", "Candidate improves measured setup WNS while satisfying DRC and area limits. M1 records the result and stops; L2 owns further search.", {"reason": "bounded_candidate_accepted"}
        return "stop", "Candidate does not improve measured setup WNS. Preserve both Runtime receipts and stop; M1 does not invent another optimization action.", {"reason": "no_measured_improvement"}
