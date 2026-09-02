import dataclasses

import pytest

from openroad_platform_analysis import (diagnosis_packet, paired_replica_seeds,
                                        intermediate_proxy_score,
                                        observed_hypervolume_trace,
                                        relative_utility, stalled_decision,
                                        summarize_replicates)
from openroad_platform_contracts import (EvidencePointer, LearningContext,
                                         LearningObservation, ObjectiveSpec)


def observation(index, area, slack, *, status="succeeded"):
    context = LearningContext(
        design_id="gcd", design_fingerprint="a" * 64, platform="nangate45",
        pdk_id="nangate45", toolchain_id="orfs-fixed", flow_stage="finish",
        metric_parser_version="runtime-v2",
    )
    return LearningObservation(
        observation_id=f"obs-{index}", context=context,
        parameters={"place_density": .5}, metrics={"area_um2": area, "setup_wns_ns": slack},
        metric_units={"area_um2": "um2", "setup_wns_ns": "ns"}, status=status,
        cost_seconds=1, run_id=f"run-{index}", attempt_id=f"attempt-{index}",
        evidence=(EvidencePointer(ref=f"run:run-{index}", sha256=str(index) * 64),),
    )


def test_replicate_summary_utility_and_stall_are_not_best_single_run():
    objectives = (ObjectiveSpec("area_um2", "min", .6),
                  ObjectiveSpec("setup_wns_ns", "max", .4))
    baseline = summarize_replicates(
        [observation(1, 100, .10), observation(2, 102, .12), observation(3, 98, .11)],
        objectives, ({"metric": "setup_wns_ns", "operator": ">=", "threshold": 0},))
    candidate = summarize_replicates(
        [observation(4, 90, .08), observation(5, 110, .09), observation(6, 92, .10)],
        objectives, ({"metric": "setup_wns_ns", "operator": ">=", "threshold": 0},))
    assert candidate["metrics"]["area_um2"]["median"] == 92
    assert candidate["metrics"]["area_um2"]["maximum"] == 110
    utility = relative_utility(candidate, baseline, objectives)
    assert utility is not None
    rejected = stalled_decision(candidate_utility=utility, best_utility=utility,
                                minimum_relative_improvement=.01, stalled_rounds=2)
    assert rejected["promoted"] is False
    assert rejected["stalled_rounds"] == 3


def test_failed_constraint_blocks_promotion_and_produces_non_executable_diagnosis():
    objectives = (ObjectiveSpec("area_um2", "min"),)
    summary = summarize_replicates(
        [observation(1, 90, -.1), observation(2, 91, .1)], objectives,
        ({"metric": "setup_wns_ns", "operator": ">=", "threshold": 0},))
    assert summary["eligible"] is False
    assert relative_utility(summary, summary, objectives) is None
    packet = diagnosis_packet([{"round": 1, "summary": summary}], objectives)
    assert packet["execution_allowed"] is False
    assert packet["violated_constraints"]


def test_diagnosis_counts_all_replica_failure_without_crashing():
    objectives = (ObjectiveSpec("area_um2", "min"),)
    packet = diagnosis_packet([
        {"round": 1, "summary": None, "decision": "all_replicas_failed"},
        {"round": 2, "summary": {"failure_rate": .5, "constraints": []}},
    ], objectives)
    assert packet["failed_rounds"] == 2
    assert packet["last_round"] == 2


def test_first_feasible_candidate_replaces_an_infeasible_baseline_even_if_relative_qor_is_negative():
    decision = stalled_decision(
        candidate_utility=-.2, best_utility=-1.0,
        minimum_relative_improvement=.01, stalled_rounds=0,
        has_feasible_incumbent=False)
    assert decision["promoted"] is True
    assert decision["incremental_improvement"] is None
    assert decision["reason"] == "first hard-constraint-feasible candidate"


def test_paired_replica_seeds_are_stable_distinct_and_seed_sensitive():
    first = paired_replica_seeds(20260825, 5)
    assert first == paired_replica_seeds(20260825, 5)
    assert len(first) == len(set(first)) == 5
    assert first != paired_replica_seeds(20260826, 5)


def test_intermediate_score_is_explicitly_not_final_qor():
    objectives = (ObjectiveSpec("area_um2", "min", .6),
                  ObjectiveSpec("setup_wns_ns", "max", .4))
    baseline = summarize_replicates(
        [observation(1, 100, .10), observation(2, 102, .12)], objectives)
    proxy = intermediate_proxy_score(
        [observation(3, 90, .11)], baseline, objectives)
    assert proxy["score"] is not None
    assert proxy["eligible_for_calibration"] is True
    assert proxy["quick_metrics_are_final"] is False
    assert "never replace final QoR" in proxy["claim_boundary"]


def test_intermediate_score_prefers_explicit_proxy_namespace():
    objectives = (ObjectiveSpec("area_um2", "min", 1.0),)
    baseline = summarize_replicates([observation(1, 100, .1)], objectives)
    quick = dataclasses.replace(
        observation(2, 1, .1),
        metrics={"area_um2": 1.0, "proxy_area_um2": 90.0},
        metric_units={"area_um2": "um2", "proxy_area_um2": "um2"},
    )
    proxy = intermediate_proxy_score([quick], baseline, objectives)
    assert proxy["metric_sources"] == {"area_um2": "proxy_area_um2"}
    assert proxy["proxy_medians"] == {"area_um2": 90.0}
    assert proxy["score"] == pytest.approx(.1)


def test_hypervolume_trace_uses_only_observed_eligible_full_summaries():
    objectives = (ObjectiveSpec("area_um2", "min", .5),
                  ObjectiveSpec("setup_wns_ns", "max", .5, 1.0))
    baseline = summarize_replicates([observation(1, 100, 0)], objectives)
    history = [
        {"round": 1, "kind": "bo_candidate", "candidate_id": "a",
         "summary": summarize_replicates([observation(2, 80, .2)], objectives)},
        {"round": 2, "kind": "quick_proxy_only", "candidate_id": "fake",
         "summary": None},
        {"round": 3, "kind": "bo_candidate", "candidate_id": "b",
         "summary": summarize_replicates([observation(3, 70, .1)], objectives)},
    ]
    trace = observed_hypervolume_trace(history, objectives, baseline)
    assert len(trace["trace"]) == 2
    assert {item["candidate_id"] for item in trace["pareto"]} == {"a", "b"}
    assert trace["hypervolume"] >= trace["trace"][0]["hypervolume"]
    assert trace["predictions_included"] is False
