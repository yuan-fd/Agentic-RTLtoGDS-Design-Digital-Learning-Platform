import copy

import pytest

from openroad_platform_analysis.industrial_dse_protocol import (
    build_industrial_dse_protocol, build_stateful_l2_protocol, validate_industrial_dse_protocol,
    write_frozen_protocol,
)


def _calibration():
    return {
        "protocol": "single-knob-low-mid-high-three-paired-seeds-v1",
        "parameters": [
            {"platform": platform, "parameter": "core_utilization_pct",
             "search_eligible": True, "classification": "runtime_value_verified"}
            for platform in ("nangate45", "asap7", "sky130hd")
        ],
    }


def test_protocol_separates_common_baseline_from_full_domain(tmp_path):
    protocol = build_industrial_dse_protocol(
        calibration_report=_calibration(), orfs_commit="abc",
        toolchain_fingerprint="tool", source_snapshot={"aes": "sha"})
    assert protocol["budget_checkpoints"] == [50, 100, 200, 375, 600]
    assert len(protocol["primary_blocks"]) == 6
    assert protocol["full_domain_arm"]["search_domain"] == "calibrated_full"
    assert {item["arm_id"] for item in protocol["full_domain_arms"]} == {
        "random_full", "sobol_full", "industrial_portfolio"}
    assert "intersection" in protocol["search_domains"]["common"]
    assert protocol["statistics"]["unit"].startswith("design-PDK")
    assert "median aggregation" in protocol["statistics"]["unit"]
    assert protocol["study_id"].endswith("-r27")
    assert "node-local" in protocol["execution"]["state_storage_policy"]
    assert "content-verified" in protocol["execution"]["state_storage_policy"]
    assert "FLOW_HOME" in protocol["execution"]["external_environment_policy"]
    assert "validated pinned ORFS" in protocol["execution"][
        "external_environment_policy"]
    assert protocol["search_domains"]["common_domain_id"] == \
        "official_autotuner_independent_v2"
    assert "every common-domain arm" in protocol["search_domains"][
        "relational_parameter_policy"]
    assert "single lucky-seed" in protocol["optimization_policy"][
        "safe_anchor_replication"]
    assert "trust-region centers" in protocol["optimization_policy"][
        "replicated_incumbent_policy"]
    assert "constraints_func" in protocol["optimization_policy"][
        "tpe_constraint_handling"]
    assert "valid completed nonattainment" in protocol["stopping"][
        "nonattainment_completion"]
    assert "enumerated value sets must match" in protocol["search_domains"][
        "quantized_bound_parity"]
    assert "constant_liar=True" in protocol["optimization_policy"][
        "tpe_batch_domain_policy"]
    assert "all 2^6 paired sign flips" in protocol["statistics"][
        "exact_small_sample_policy"]
    assert "two co-primary" in protocol["statistics"]["primary_test"]
    assert "more aggregate compute" in protocol["statistics"][
        "strong_control_policy"]
    assert "identical content fingerprint" in protocol["statistics"][
        "baseline_parity_policy"]
    assert "exactly one active placement-density policy" in protocol[
        "search_domains"]["placement_density_policy"]
    assert "both study_id and protocol_digest" in protocol[
        "reproducibility"]["aggregation_binding_policy"]
    assert protocol["search_domains"]["common_parameter_names"] == [
        "core_utilization_pct", "place_density_lb_addon",
        "global_placement_padding", "cts_cluster_size",
        "cts_cluster_diameter"]
    assert "recomputes all bindings" in protocol["reproducibility"][
        "external_domain_binding_policy"]
    assert "18 seed cells are descriptive" in protocol["statistics"][
        "ablation_inference_unit"]
    assert protocol["statistics"]["ablation_co_primary_ids"] == [
        "no_gp", "no_memory", "no_edair"]
    assert "exactly three co-primary" in protocol["statistics"][
        "ablation_family_policy"]
    assert protocol["optimization_policy"][
        "surrogate_minimum_unique_configurations"] == (
            "max(32, 4 * search_dimensions)")
    assert "complete fixed" in protocol["execution"]["completion_gate"]
    assert "exact reference RTL" in protocol["search_domains"][
        "external_optimizer_design_adapter"]
    assert "Wilson 95%" in protocol["endpoint_definitions"]["empirical_attainment"]
    assert "budget+1" in protocol["optimization_policy"][
        "external_baseline_warm_start"]
    assert "protocol digest" in protocol["execution"]["external_artifact_namespace"]
    assert "botorch" in protocol["reproducibility"]["python_environment_policy"]
    assert "finite positive wall time" in protocol["metric_contract"][
        "runtime_evidence_policy"]
    assert "one-factor-at-a-time" in protocol["optimization_policy"][
        "initialization"]
    path = write_frozen_protocol(tmp_path / "protocol.json", protocol)
    assert write_frozen_protocol(path, protocol) == path


def test_protocol_digest_and_clock_gate_are_immutable():
    protocol = build_industrial_dse_protocol(
        calibration_report=_calibration(), orfs_commit="abc",
        toolchain_fingerprint="tool", source_snapshot={})
    changed = copy.deepcopy(protocol)
    changed["budget_checkpoints"][-1] = 599
    with pytest.raises(ValueError):
        validate_industrial_dse_protocol(changed)


def test_stateful_protocol_is_a_new_unpooled_algorithm_identity():
    protocol = build_stateful_l2_protocol(
        calibration_report=_calibration(), orfs_commit="abc",
        toolchain_fingerprint="tool", source_snapshot={})
    assert protocol["schema_version"] == 32
    assert protocol["study_id"].endswith("stateful-l2")
    assert protocol["full_domain_arm"]["optimizer"] == "stateful-l2-portfolio-v1"
    assert "cannot emit numeric candidates" in protocol["optimization_policy"]["stateful_l2_policy"]
    assert "at most eight" in protocol["optimization_policy"]["edair_context_policy"]
    assert "No generic shell command" in protocol["execution"]["l1_semantic_tool_policy"]
    assert "Campaign and Runner independently recompute" in protocol["execution"][
        "frozen_controller_binding_policy"]
    assert any(item["ablation_id"] == "no_state_policy" for item in protocol["ablations"])
    validate_industrial_dse_protocol(protocol)
