import pytest

from openroad_platform_execution.orfs_parameters import (
    apply_parameter_calibration, apply_parameter_search_allowlist,
    effective_configuration_id,
    orfs_parameter_config_lines,
    orfs_parameter_schema,
    orfs_optimization_profile,
    official_autotuner_independent_parameter_names,
    parameter_source_evidence,
    validate_orfs_parameters,
)
from openroad_platform_execution.orfs_config import write_design_files
from openroad_platform_analysis.run_evidence import _effective_parameters, _parameter_liveness


def test_mixed_parameters_are_canonical_and_materialized():
    values = validate_orfs_parameters({
        "core_utilization_pct": 55,
        "enable_dpo": True,
        "routing_layer_adjustment": .3,
        "global_placement_padding": 2,
        "detail_placement_padding": 1,
    }, platform="asap7")
    assert values["enable_dpo"] == 1
    lines = orfs_parameter_config_lines(values, platform="asap7")
    assert "export CORE_UTILIZATION = 55" in lines
    assert "export ENABLE_DPO = 1" in lines


def test_registry_rejects_dead_unsafe_and_inconsistent_parameters():
    with pytest.raises(ValueError, match="Unsupported"):
        validate_orfs_parameters({"clock_period_ns": 20}, platform="asap7")
    with pytest.raises(ValueError, match="cannot exceed"):
        validate_orfs_parameters({
            "global_placement_padding": 1, "detail_placement_padding": 2,
        }, platform="asap7")


def test_official_hyperopt_domain_removes_unrepresentable_dependent_knob(tmp_path):
    variables = tmp_path / "variables.yaml"
    variables.write_text("\n".join([
        "CORE_UTILIZATION: {tunable: 1}",
        "CELL_PAD_IN_SITES_GLOBAL_PLACEMENT: {tunable: 1}",
        "CELL_PAD_IN_SITES_DETAIL_PLACEMENT: {tunable: 1}",
        "CTS_CLUSTER_SIZE: {tunable: 1}",
    ]))
    names = official_autotuner_independent_parameter_names(
        orfs_optimization_profile("asap7"), variables)
    assert "global_placement_padding" in names
    assert "detail_placement_padding" not in names
    assert {"core_utilization_pct", "cts_cluster_size"} <= names
    with pytest.raises(ValueError, match="calibrated range"):
        validate_orfs_parameters({"core_utilization_pct": 79}, platform="asap7")
    with pytest.raises(ValueError, match="calibrated range"):
        validate_orfs_parameters({"global_placement_padding": 4}, platform="asap7")
    with pytest.raises(ValueError, match="alternative"):
        validate_orfs_parameters({
            "place_density": .5, "place_density_lb_addon": .2,
        }, platform="asap7")


def test_effective_id_uses_canonical_values_and_platform():
    first = effective_configuration_id({"enable_dpo": True}, platform="asap7")
    second = effective_configuration_id({"enable_dpo": 1}, platform="asap7")
    third = effective_configuration_id({"enable_dpo": 1}, platform="sky130hd")
    assert first == second
    assert first != third
    schema = orfs_parameter_schema()
    assert len(schema["parameters"]) == 12
    assert schema["liveness_rule_version"] == "orfs-runtime-patterns-v2"
    assert "clock_period_ns" in schema["frozen_constraints"]


def test_generated_orfs_config_contains_typed_vector(tmp_path):
    rtl = tmp_path / "top.v"
    rtl.write_text("module top(input clk); endmodule\n")
    config = write_design_files(
        workdir=tmp_path / "run", rtl_path=rtl, design="top",
        platform="asap7", clock="clk", clock_period_ns=10,
        core_utilization_pct=30, place_density=.45,
        flow_parameters={"core_utilization_pct": 55, "enable_dpo": False,
                         "cts_cluster_size": 20},
    )
    text = config.read_text()
    assert "export CORE_UTILIZATION = 55" in text
    assert "export ENABLE_DPO = 0" in text
    assert "export CTS_CLUSTER_SIZE = 20" in text
    assert "export CLOCK_PERIOD = 10000" in text
    assert "create_clock -name clk -period 10000" in (
        tmp_path / "run/designs/asap7/top/constraint.sdc").read_text()


def test_evidence_distinguishes_config_materialization_from_runtime_liveness(tmp_path):
    design_dir = tmp_path / "designs/asap7/top"
    design_dir.mkdir(parents=True)
    (design_dir / "config.mk").write_text(
        "export CORE_UTILIZATION = 55\nexport ENABLE_DPO = 1\n")
    schema = orfs_parameter_schema()
    (tmp_path / "parameter_contract.json").write_text(__import__("json").dumps({
        "registry": schema,
        "requested_parameters": {"core_utilization_pct": 55, "enable_dpo": 1},
        "effective_configuration_id": "orfs-effective-test",
    }))
    effective = _effective_parameters(tmp_path, "asap7", "top", {})
    evidence = _parameter_liveness(tmp_path, effective)
    assert evidence["status"] == "materialized"
    assert all(row["runtime_observed"] is False for row in evidence["parameters"])
    assert all(row["evidence_level"] == "config_materialized" for row in evidence["parameters"])


def test_runtime_liveness_requires_value_bearing_log_evidence(tmp_path):
    design_dir = tmp_path / "designs/nangate45/top"
    design_dir.mkdir(parents=True)
    (design_dir / "config.mk").write_text(
        "export CORE_UTILIZATION = 55\n"
        "export TNS_END_PERCENT = 100\n"
        "export CTS_CLUSTER_SIZE = 20\n"
        "export CTS_CLUSTER_DIAMETER = 50.0\n"
    )
    schema = orfs_parameter_schema()
    requested = {"core_utilization_pct": 55, "tns_end_percent": 100,
                 "cts_cluster_size": 20, "cts_cluster_diameter": 50.0}
    source = [{"name": item["name"], "consumer_declared": True,
               "runtime_patterns": item["runtime_patterns"], "stage": item["stage"]}
              for item in schema["parameters"] if item["name"] in requested]
    (tmp_path / "parameter_contract.json").write_text(__import__("json").dumps({
        "registry": schema, "requested_parameters": requested,
        "source_evidence": source, "effective_configuration_id": "test",
    }))
    log = tmp_path / "logs/flow.log"
    log.parent.mkdir(parents=True)
    log.write_text(
        "[INFO IFP-0107] Defining die area using utilization: 55.00%\n"
        "repair_timing -repair_tns 100 -verbose\n"
        "clock_tree_synthesis -sink_clustering_size 20 "
        "-sink_clustering_max_diameter 50.0\n"
    )
    evidence = _parameter_liveness(
        tmp_path, _effective_parameters(tmp_path, "nangate45", "top", {})
    )
    assert evidence["liveness_rule_version"] == "orfs-runtime-patterns-v2"
    assert {row["name"] for row in evidence["parameters"]
            if row["evidence_level"] == "runtime_value_observed"} == set(requested)


def test_source_evidence_binds_parameter_to_pinned_consumer(tmp_path):
    script = tmp_path / "scripts/detail_place.tcl"
    script.parent.mkdir(parents=True)
    script.write_text("if { $::env(ENABLE_DPO) } { improve_placement }\n")
    rows = parameter_source_evidence(tmp_path, {"enable_dpo": 1})
    assert rows[0]["consumer_declared"] is True
    assert len(rows[0]["consumer_sha256"]) == 64
    assert rows[0]["stage"] == "place"


def test_industrial_profile_is_server_owned_mixed_and_freezes_clock():
    profile = orfs_optimization_profile("asap7")
    assert len(profile["parameter_space"]) == 11
    assert {item["kind"] for item in profile["parameter_space"]} >= {"int", "float", "bool"}
    assert profile["baseline"]["core_utilization_pct"] == 65
    assert "clock_period_ns" in profile["frozen_constraints"]
    stages = {item["name"]: item["stage"] for item in profile["parameter_space"]}
    assert stages["place_density_lb_addon"] == "place"
    assert stages["routing_layer_adjustment"] == "floorplan"
    with pytest.raises(ValueError, match="No calibrated"):
        orfs_optimization_profile("unknown-pdk")


def test_calibration_can_only_remove_unverified_parameters():
    profile = orfs_optimization_profile("asap7")
    report = {
        "protocol": "single-knob-low-mid-high-three-paired-seeds-v1",
        "evaluation_count": 12, "claim_boundary": "liveness only",
        "parameters": [
            {"platform": "asap7", "parameter": item["name"],
             "search_eligible": item["name"] in {"core_utilization_pct", "enable_dpo"},
             "classification": "runtime_value_verified" if item["name"] == "core_utilization_pct"
                               else "runtime_switch_verified" if item["name"] == "enable_dpo"
                               else "unresolved"}
            for item in profile["parameter_space"]
        ],
    }
    filtered = apply_parameter_calibration(profile, report)
    assert {item["name"] for item in filtered["parameter_space"]} == {
        "core_utilization_pct", "enable_dpo"}
    assert filtered["baseline"] == profile["baseline"]
    assert set(filtered["search_baseline"]) == {"core_utilization_pct", "enable_dpo"}
    assert len(filtered["fixed_parameters"]) == 9
    assert len(filtered["parameter_calibration"]["excluded"]) == 9
    assert filtered["frozen_constraints"] == profile["frozen_constraints"]


def test_fair_search_allowlist_keeps_excluded_knobs_fixed():
    profile = orfs_optimization_profile("nangate45")
    restricted = apply_parameter_search_allowlist(
        profile, {"core_utilization_pct", "cts_cluster_size"},
        domain_id="test-common-domain")
    assert {item["name"] for item in restricted["parameter_space"]} == {
        "core_utilization_pct", "cts_cluster_size"}
    assert restricted["search_baseline"] == {
        "core_utilization_pct": 55, "cts_cluster_size": 20}
    assert restricted["fixed_parameters"]["enable_dpo"] == 1
    assert restricted["baseline"] == profile["baseline"]


def test_calibration_cannot_inject_a_new_parameter():
    profile = orfs_optimization_profile("asap7")
    report = {"protocol": "single-knob-low-mid-high-three-paired-seeds-v1",
              "parameters": [{"platform": "asap7", "parameter": "clock_period_ns",
                              "search_eligible": True}]}
    with pytest.raises(ValueError, match="outside the profile"):
        apply_parameter_calibration(profile, report)
