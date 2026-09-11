from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from openroad_platform_analysis.parameter_calibration import aggregate_parameter_calibration


def _script_module():
    path = Path(__file__).resolve().parents[1] / "scripts/calibrate_orfs_parameters.py"
    spec = importlib.util.spec_from_file_location("calibrate_orfs_parameters", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_plan_is_single_factor_repeated_and_constraint_safe(tmp_path):
    module = _script_module()
    cases = module.build_cases(
        output=tmp_path, platforms=["nangate45"], seeds=[101, 211, 307],
        rtl=tmp_path / "gcd.v",
    )
    assert len(cases) == 90
    addon = [row for row in cases if row["parameter"] == "place_density_lb_addon"]
    assert {row["requested_value"] for row in addon} == {0, .25, .50}
    detail = [row for row in cases if row["parameter"] == "detail_placement_padding"]
    assert all(row["control_parameters"]["global_placement_padding"] == 3 for row in detail)
    assert all(row["control_parameters"]["place_density_lb_addon"] == 0 for row in detail)
    assert all(row["control_parameters"]["core_utilization_pct"] == 20 for row in detail)
    global_padding = [row for row in cases if row["parameter"] == "global_placement_padding"]
    assert all(row["control_parameters"]["place_density_lb_addon"] == 0
               for row in global_padding)
    assert all(row["control_parameters"]["core_utilization_pct"] == 20
               for row in global_padding)
    cts = [row for row in cases if row["parameter"] in {
        "cts_cluster_size", "cts_cluster_diameter"}]
    assert all(row["control_parameters"]["place_density_lb_addon"] == 0 for row in cts)
    assert all(row["control_parameters"]["core_utilization_pct"] == 20 for row in cts)
    assert all(row["conditioning"] == {
        "core_utilization_pct": 20, "place_density_lb_addon": 0.0} for row in cts)
    assert all(len(row["case_id"].rsplit("-", 1)[-1]) == 10 for row in cases)
    assert {row["or_seed"] for row in cases} == {101, 211, 307}


def _case(tmp_path, value, seed, *, observed):
    run = tmp_path / f"run-{value}-{seed}"
    analysis = run / "analysis"; analysis.mkdir(parents=True)
    (run / "run_result.json").write_text(json.dumps({"status": "succeeded"}))
    (analysis / "parameter_liveness.json").write_text(json.dumps({
        "liveness_rule_version": "test-v1", "parameters": [{
            "name": "knob", "evidence_level": "runtime_value_observed" if observed else "consumer_stage_completed",
            "runtime_observed": observed, "materialized_match": True,
            "consumer_declared": True, "stage_completed": True,
        }],
    }))
    (analysis / "stage_metrics.json").write_text(json.dumps({
        "stages": {"place": {"metrics": {"area": value}}},
    }))
    odb = run / "results/nangate45/gcd/base/3_place.odb"; odb.parent.mkdir(parents=True)
    odb.write_text(f"odb-{value}")
    return {"workdir": str(run), "platform": "nangate45", "design": "gcd",
            "parameter": "knob", "requested_value": value,
            "target_stage": "place", "or_seed": seed}


def test_aggregate_requires_repeated_value_bearing_evidence(tmp_path):
    cases = [_case(tmp_path, value, seed, observed=True)
             for seed in (101, 211, 307) for value in (1, 2, 3)]
    report = aggregate_parameter_calibration(cases)
    row = report["parameters"][0]
    assert row["classification"] == "runtime_value_verified"
    assert row["search_eligible"] is True
    assert row["odb_divergent_paired_seeds"] == 3
    assert report["claim_boundary"].endswith("full-flow experiments.")
