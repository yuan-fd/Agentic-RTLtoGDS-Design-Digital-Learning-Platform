import importlib.util
from pathlib import Path
import pytest

from openroad_platform_analysis.industrial_dse_protocol import build_industrial_dse_protocol


def _module():
    path = Path(__file__).resolve().parents[1] / "scripts/analyze_industrial_dse_ablations.py"
    spec = importlib.util.spec_from_file_location("ablation_analysis", path)
    module = importlib.util.module_from_spec(spec); assert spec.loader
    spec.loader.exec_module(module); return module


def test_ablation_analysis_keeps_single_replica_out_of_mechanism_tests():
    module = _module()
    protocol = build_industrial_dse_protocol(
        calibration_report={
            "protocol": "single-knob-low-mid-high-three-paired-seeds-v1",
            "parameters": [{"platform": p, "search_eligible": True}
                           for p in ("nangate45", "asap7", "sky130hd")],
        }, orfs_commit="abc", toolchain_fingerprint="tool", source_snapshot={})
    primary, ablations = [], []
    for block in protocol["primary_blocks"]:
        for seed in protocol["optimizer_seeds"]:
            manifest = {
                "platform": block["platform"], "design": block["design"],
                "optimizer_seed": seed, "arm": "portfolio", "ablation": "none",
                "frozen_study_protocol_digest": protocol["protocol_digest"],
            }
            primary.append({"manifest": manifest, "anytime_hypervolume": {
                "checkpoint_normalized_auc": {"200": 2.0}},
                "runtime_cost": {"total_run_wall_seconds": 100.0,
                                 "missing_duration_count": 0}})
            for item in protocol["ablations"]:
                ablations.append({
                    "manifest": {**manifest, "ablation": item["ablation_id"]},
                    "logical_budget": 200,
                    "anytime_hypervolume": {"normalized_auc": 1.0},
                    "runtime_cost": {"total_run_wall_seconds": (
                        150.0 if item["ablation_id"] == "no_multifidelity" else 100.0),
                                     "missing_duration_count": 0},
                })
    result = module.analyze_ablations(
        {"all_cells_eligible": True, "cells": primary},
        {"all_cells_eligible": True, "cells": ablations}, protocol)
    assert "single_replica_error_control" not in result["mechanism_ablations"]
    assert len(result["mechanism_ablations"]) == 8
    assert "no_safe_initialization" in result["mechanism_ablations"]
    assert result["paired_unit_count"] == 6
    assert result["descriptive_seed_cell_count"] == 18
    assert all(row["paired_unit_count"] == 6
               for row in result["mechanism_ablations"].values())
    assert all(row["descriptive_seed_cell_count"] == 18
               for row in result["mechanism_ablations"].values())
    assert result["co_primary_ablation_family"] == ["no_edair", "no_gp", "no_memory"]
    assert all("holm_adjusted_p_value" in result["mechanism_ablations"][name]
               for name in result["co_primary_ablation_family"])
    assert all("holm_adjusted_p_value" not in row
               for name, row in result["mechanism_ablations"].items()
               if name not in result["co_primary_ablation_family"])
    assert len(result["single_replica_error_control"]["rows"]) == 18
    assert result["multifidelity_efficiency"]["median_saved_fraction"] == pytest.approx(1 / 3)
