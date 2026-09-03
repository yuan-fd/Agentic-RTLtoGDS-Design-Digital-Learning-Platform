from __future__ import annotations

import dataclasses
import numpy as np

from openroad_platform_analysis.optimizer_plugins import (
    AdaptiveTrustRegionQNEHVIOptimizer, BoTorchQNEHVIOptimizer,
    IndustrialOptimizerPortfolio, MixedParameterEncoder, OptunaTPEOptimizer,
    RandomOptimizer, SafeAnchoredSobolOptimizer, SobolOptimizer,
    _observation_is_feasible, default_optimizer_registry,
)
from openroad_platform_contracts import (
    EvidencePointer, LearningContext, LearningObservation, ObjectiveSpec,
    OptimizationStudy, ParameterSpec,
)


SHA = "a" * 64


def _study(max_runs=100):
    context = LearningContext(
        design_id="gcd", design_fingerprint=SHA, platform="asap7",
        pdk_id="asap7", toolchain_id="orfs-pinned", flow_stage="finish",
        metric_parser_version="metrics21",
    )
    return context, OptimizationStudy(
        study_id="mixed-study", design_id="gcd",
        context_fingerprint=context.fingerprint,
        parameter_space=(
            ParameterSpec("util", 20, 80, kind="int", step=1, stage="floorplan"),
            ParameterSpec("dpo", None, None, kind="bool", stage="place"),
            ParameterSpec("effort", None, None, kind="categorical",
                          choices=("low", "high"), stage="route",
                          active_when={"dpo": 1}),
        ),
        objectives=(ObjectiveSpec("area", "min"), ObjectiveSpec("wns", "max")),
        max_runs=max_runs, seed=23,
    )


def _observation(context, index, parameters, *, succeeded=True):
    util = float(parameters["util"])
    dpo = float(parameters["dpo"])
    effort = float(parameters.get("effort") == "high")
    return LearningObservation(
        observation_id=f"obs-{index}", context=context, parameters=parameters,
        metrics={"area": 110 - .20 * util + 2 * dpo,
                 "wns": -.5 + .01 * util + .10 * effort} if succeeded else {},
        metric_units={"area": "um2", "wns": "ns"} if succeeded else {},
        status="succeeded" if succeeded else "failed", cost_seconds=10,
        run_id=f"run-{index}", attempt_id=f"attempt-{index}",
        evidence=(EvidencePointer(ref=f"artifact:{index}", sha256=f"{index % 10}" * 64),),
    )


def test_mixed_encoder_quantizes_conditions_and_is_deterministic():
    _, study = _study()
    encoder = MixedParameterEncoder(study.parameter_space)
    inactive = encoder.decode_unit((.5, .1, .9))
    active = encoder.decode_unit((.5, .9, .9))
    assert inactive == {"util": 50, "dpo": 0}
    assert active == {"util": 50, "dpo": 1, "effort": "high"}
    assert encoder.encoded_dimension == 4
    assert np.allclose(encoder.encode(active), [.5, 1, 0, 1])
    assert encoder.sobol_candidates(16, seed=3) == encoder.sobol_candidates(16, seed=3)


def test_feasibility_label_uses_qor_constraints_not_process_success_only():
    context, _ = _study()
    point = {"util": 40, "dpo": 0}
    violating = _observation(context, 1, point)
    feasible = dataclasses.replace(
        violating, observation_id="obs-feasible", run_id="run-feasible",
        attempt_id="attempt-feasible", metrics={**violating.metrics, "wns": .1})
    rules = ({"metric": "wns", "operator": ">=", "threshold": 0.0},)
    assert violating.status == "succeeded"
    assert _observation_is_feasible(violating, rules) is False
    assert _observation_is_feasible(feasible, rules) is True


def test_sobol_backend_emits_unique_nonexecuting_mixed_proposals():
    _, study = _study()
    proposals = SobolOptimizer().propose_batch(
        study, (), batch_size=8, baseline_metrics={"area": 100, "wns": 0},
    )
    assert len(proposals) == 8
    assert len({tuple(sorted(item.parameters.items())) for item in proposals}) == 8
    assert all(item.execution_allowed is False for item in proposals)
    assert default_optimizer_registry().resolve("sobol-scrambled-mixed-v1")


def test_safe_cold_start_uses_observed_feasible_anchor_before_combinations():
    context, study = _study()
    anchor = {"util": 50, "dpo": 0}
    observation = _observation(context, 0, anchor)
    replica = dataclasses.replace(
        observation, observation_id="obs-anchor-2", run_id="run-anchor-2",
        attempt_id="attempt-anchor-2")
    proposals = SafeAnchoredSobolOptimizer().propose_batch(
        study, (observation, replica), batch_size=2,
        baseline_metrics={"area": 100, "wns": 0},
    )
    assert len(proposals) == 2
    assert all(item.model_metadata["anchor_observed_feasible"] is True
               for item in proposals)
    assert all(item.model_metadata["high_order_interactions_deferred"] is True
               for item in proposals)
    assert all(item.model_metadata["anchor_replica_count"] == 2
               for item in proposals)
    assert default_optimizer_registry().resolve(
        "safe-anchored-sobol-mixed-v1")


def test_safe_cold_start_rejects_lucky_seed_when_replica_violates_constraint():
    context, original = _study()
    study = dataclasses.replace(original, hard_constraints=(
        {"metric": "wns", "operator": ">=", "threshold": 0.0},))
    anchor = {"util": 50, "dpo": 0}
    lucky = _observation(context, 0, anchor)
    violating = dataclasses.replace(
        lucky, observation_id="obs-violating", run_id="run-violating",
        attempt_id="attempt-violating",
        metrics={**lucky.metrics, "wns": -0.1})
    proposals = SafeAnchoredSobolOptimizer().propose_batch(
        study, (lucky, violating), batch_size=2,
        baseline_metrics={"area": 100, "wns": 0})
    assert all(item.model_metadata["backend_id"] ==
               "sobol-scrambled-mixed-v1" for item in proposals)
    assert all("anchor_observed_feasible" not in item.model_metadata
               for item in proposals)


def test_quick_only_candidate_can_be_excluded_without_fabricating_observation():
    _, study = _study()
    first = SobolOptimizer().propose_batch(
        study, (), batch_size=1, baseline_metrics={"area": 100, "wns": 0},
    )[0]
    replacement = SobolOptimizer().propose_batch(
        study, (), batch_size=1, baseline_metrics={"area": 100, "wns": 0},
        excluded_parameters=(first.parameters,),
    )[0]
    assert replacement.parameters != first.parameters
    assert replacement.iteration == first.iteration == 0


def test_random_and_tpe_are_real_deduplicated_comparison_backends():
    context, study = _study()
    seed_points = MixedParameterEncoder(study.parameter_space).sobol_candidates(24, seed=17)
    observations = tuple(_observation(context, index, item)
                         for index, item in enumerate(seed_points))
    for optimizer in (RandomOptimizer(), OptunaTPEOptimizer()):
        first = optimizer.propose_batch(
            study, observations, batch_size=4,
            baseline_metrics={"area": 100, "wns": 0},
        )
        second = optimizer.propose_batch(
            study, observations, batch_size=4,
            baseline_metrics={"area": 100, "wns": 0},
        )
        assert [item.parameters for item in first] == [item.parameters for item in second]
        assert len({tuple(sorted(item.parameters.items())) for item in first}) == 4


def test_tpe_excludes_infrastructure_failure_from_sampler_history():
    context, study = _study()
    points = MixedParameterEncoder(study.parameter_space).sobol_candidates(8, seed=41)
    observations = [_observation(context, index, item)
                    for index, item in enumerate(points[:7])]
    failed = _observation(context, 20, points[7], succeeded=False)
    observations.append(dataclasses.replace(
        failed, status="lost", failure_category="worker_lost"))
    proposal = OptunaTPEOptimizer().propose_batch(
        study, observations, batch_size=1,
        baseline_metrics={"area": 100.0, "wns": 0.0},
    )[0]
    assert proposal.model_metadata[
        "infrastructure_failures_excluded_from_model"] == 1


def test_tpe_declares_hard_constraint_aware_sampling():
    context, original = _study()
    study = dataclasses.replace(original, hard_constraints=(
        {"metric": "wns", "operator": ">=", "threshold": 0.0},))
    points = MixedParameterEncoder(study.parameter_space).sobol_candidates(24, seed=57)
    observations = tuple(_observation(context, index, item)
                         for index, item in enumerate(points))
    proposal = OptunaTPEOptimizer().propose_batch(
        study, observations, batch_size=1,
        baseline_metrics={"area": 100, "wns": 0})[0]
    assert "constraints_func" in proposal.model_metadata["constraint_handling"]


def test_tpe_projects_relational_parameters_into_shared_legal_domain():
    context, original = _study()
    study = dataclasses.replace(original, parameter_space=(
        ParameterSpec("global_pad", 0, 3, kind="int", step=1, stage="place"),
        ParameterSpec("detail_pad", 0, 3, kind="int", step=1, stage="place",
                      less_than_or_equal_to="global_pad"),
    ))
    observations = ()
    proposals = OptunaTPEOptimizer().propose_batch(
        study, observations, batch_size=8,
        baseline_metrics={"area": 100, "wns": 0})
    assert all(item.parameters["detail_pad"] <= item.parameters["global_pad"]
               for item in proposals)


def test_botorch_backend_fits_ard_models_and_returns_deduplicated_batch():
    context, study = _study()
    encoder = MixedParameterEncoder(study.parameter_space)
    parameters = encoder.sobol_candidates(12, seed=11)
    observations = tuple(_observation(context, index, item, succeeded=index != 2)
                         for index, item in enumerate(parameters))
    optimizer = BoTorchQNEHVIOptimizer(pool_size=256, minimum_initial=8)
    proposals = optimizer.propose_batch(
        study, observations, batch_size=2,
        baseline_metrics={"area": 100.0, "wns": 0.0},
    )
    assert len(proposals) == 2
    assert len({tuple(sorted(item.parameters.items())) for item in proposals}) == 2
    assert all(item.execution_allowed is False for item in proposals)
    assert all(item.acquisition_value >= 0 for item in proposals)
    assert all(len(item.predictions) == len(study.objectives) for item in proposals)
    assert all(prediction.source == "predicted" for item in proposals
               for prediction in item.predictions)
    assert all(item.model_metadata["has_fitted_surrogate"] is True
               for item in proposals)
    assert all("ard_lengthscales" in item.model_metadata for item in proposals)


def test_botorch_excludes_infrastructure_failure_from_model_but_keeps_audit_count():
    context, study = _study()
    parameters = MixedParameterEncoder(study.parameter_space).sobol_candidates(10, seed=29)
    observations = [_observation(context, index, item)
                    for index, item in enumerate(parameters[:8])]
    infrastructure = _observation(context, 20, parameters[8], succeeded=False)
    observations.append(dataclasses.replace(
        infrastructure, status="lost", failure_category="worker_lost"))
    proposal = BoTorchQNEHVIOptimizer(
        pool_size=256, minimum_initial=8,
    ).propose_batch(
        study, observations, batch_size=1,
        baseline_metrics={"area": 100.0, "wns": 0.0},
    )[0]
    assert proposal.model_metadata["has_fitted_surrogate"] is True
    assert proposal.model_metadata[
        "infrastructure_failures_excluded_from_model"] == 1


def test_replicas_estimate_noise_but_do_not_fake_initial_design_coverage():
    context, study = _study()
    one = {"util": 50, "dpo": 0}
    replicas = tuple(_observation(context, index, one) for index in range(12))
    proposal = BoTorchQNEHVIOptimizer(pool_size=256, minimum_initial=8).propose_batch(
        study, replicas, batch_size=1, baseline_metrics={"area": 100, "wns": 0},
    )[0]
    assert proposal.parameters != one
    assert proposal.acquisition_value == 0  # Sobol initialization, not a falsely trained GP.


def test_evidence_gated_failure_configuration_is_excluded_from_initialization():
    _, study = _study()
    first = SobolOptimizer().propose_batch(
        study, (), batch_size=1, baseline_metrics={"area": 100, "wns": 0})[0]
    forbidden = __import__("hashlib").sha256(__import__("json").dumps(
        first.parameters, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    replacement = BoTorchQNEHVIOptimizer(
        pool_size=256, minimum_initial=8,
        forbidden_configuration_ids=(forbidden,),
    ).propose_batch(study, (), batch_size=1,
                    baseline_metrics={"area": 100, "wns": 0})[0]
    assert replacement.parameters != first.parameters


def test_portfolio_routes_cold_start_and_stall_with_auditable_evidence():
    context, study = _study()
    cold = IndustrialOptimizerPortfolio(minimum_initial=8).propose_batch(
        study, (), batch_size=2, baseline_metrics={"area": 100, "wns": 0})
    assert all(item.model_metadata["portfolio_route"] ==
               "cold_start_safe_anchored_space_filling"
               for item in cold)

    # Constant repeated-quality configurations make the lack of progress
    # explicit and route the next batch into a contracted local region.
    parameters = [{"util": 30 + index, "dpo": 0} for index in range(8)]
    observations = []
    for index, item in enumerate(parameters):
        base = _observation(context, index, item)
        first = LearningObservation(
            **{**base.__dict__, "metrics": {"area": 100.0, "wns": 0.0}}
        )
        observations.extend((first, dataclasses.replace(
            first, observation_id=f"obs-{index}-replica", run_id=f"run-{index}-replica",
            attempt_id=f"attempt-{index}-replica")))
    local = IndustrialOptimizerPortfolio(minimum_initial=8, routing_hints=({
        "kind": "parameter_sensitivity", "status": "active",
        "fingerprint": "f" * 64,
        "payload": {"parameter": "util", "metric": "area"},
    },)).propose_batch(
        study, observations, batch_size=1,
        baseline_metrics={"area": 100, "wns": 0})[0]
    assert local.model_metadata["portfolio_route"] == "stalled_local_trust_region"
    assert local.model_metadata["trust_region"]["radius"] < 1
    assert local.model_metadata["trust_region"]["stage_focus"] == "floorplan"
    assert local.model_metadata["route_evidence"]["stage_focus"] == "floorplan"
    assert local.model_metadata["portfolio_backend_id"] == "industrial-dse-portfolio-v1"
    assert default_optimizer_registry().resolve(
        AdaptiveTrustRegionQNEHVIOptimizer.backend_id)


def test_portfolio_does_not_treat_worker_loss_as_parameter_failure_or_coverage():
    context, study = _study()
    points = MixedParameterEncoder(study.parameter_space).sobol_candidates(10, seed=37)
    observations = [_observation(context, 0, points[0])]
    for index, parameters in enumerate(points[1:8], start=1):
        failed = _observation(context, index, parameters, succeeded=False)
        observations.append(dataclasses.replace(
            failed, status="lost", failure_category="worker_lost"))
    proposal = IndustrialOptimizerPortfolio(minimum_initial=8).propose_batch(
        study, observations, batch_size=1,
        baseline_metrics={"area": 100, "wns": 0},
    )[0]
    assert proposal.model_metadata["portfolio_route"] == (
        "cold_start_safe_anchored_space_filling")
    route = proposal.model_metadata["route_evidence"]
    assert route["unique_configurations"] == 1
    assert route["observation_failure_rate"] == 0
    assert route["infrastructure_failures_excluded_from_routing"] == 7


def test_portfolio_ablation_switches_disable_mechanisms_in_model_evidence():
    context, study = _study()
    observations = []
    for index in range(8):
        base = _observation(context, index, {"util": 30 + index, "dpo": 0})
        first = dataclasses.replace(base, metrics={"area": 100.0, "wns": 0.0})
        observations.extend((first, dataclasses.replace(
            first, observation_id=f"obs-{index}-replica", run_id=f"run-{index}-replica",
            attempt_id=f"attempt-{index}-replica")))
    proposal = IndustrialOptimizerPortfolio(
        minimum_initial=8,
        routing_hints=({
            "kind": "parameter_sensitivity", "status": "active",
            "fingerprint": "f" * 64,
            "payload": {"parameter": "util", "metric": "area"},
        },),
        use_feasibility_model=False,
        use_trust_region=False,
        use_stage_focus=False,
    ).propose_batch(
        study, observations, batch_size=1,
        baseline_metrics={"area": 100, "wns": 0})[0]
    evidence = proposal.model_metadata["route_evidence"]
    assert proposal.model_metadata["portfolio_route"] == (
        "stalled_global_multiobjective_no_trust_region")
    assert proposal.model_metadata["trust_region"] is None
    assert proposal.model_metadata["feasibility_model_enabled"] is False
    assert evidence["feasibility_model_enabled"] is False
    assert evidence["trust_region_enabled"] is False
    assert evidence["stage_focus_enabled"] is False
    assert evidence["stage_focus"] is None


def test_trust_region_never_centers_on_hard_constraint_violation():
    context, study = _study()
    study = dataclasses.replace(study, hard_constraints=(
        {"metric": "wns", "operator": ">=", "threshold": 0.0},))
    observations = []
    for index in range(8):
        base = _observation(context, index, {"util": 30 + index, "dpo": 0})
        # Infeasible timing looks attractive in area. It must not become the
        # local-search incumbent merely because its scalar objective is large.
        observations.append(dataclasses.replace(
            base, metrics={"area": 50.0, "wns": -1.0}))
    proposal = IndustrialOptimizerPortfolio(minimum_initial=8).propose_batch(
        study, observations, batch_size=1,
        baseline_metrics={"area": 100, "wns": 0})[0]
    assert proposal.model_metadata["portfolio_route"] == \
        "global_constrained_multiobjective"
    assert proposal.model_metadata["trust_region"] is None
