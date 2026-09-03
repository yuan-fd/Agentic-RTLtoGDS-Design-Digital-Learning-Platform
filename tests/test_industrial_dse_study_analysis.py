import importlib.util
from pathlib import Path

from openroad_platform_analysis.industrial_dse_protocol import (
    build_industrial_dse_protocol,
)


def _module():
    path = Path(__file__).resolve().parents[1] / "scripts/analyze_industrial_dse_study.py"
    spec = importlib.util.spec_from_file_location("industrial_analysis", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_analysis_requires_and_uses_complete_paired_cells(monkeypatch):
    module = _module()
    protocol = build_industrial_dse_protocol(
        calibration_report={
            "protocol": "single-knob-low-mid-high-three-paired-seeds-v1",
            "parameters": [{"platform": platform, "search_eligible": True}
                           for platform in ("nangate45", "asap7", "sky130hd")],
        }, orfs_commit="abc", toolchain_fingerprint="tool", source_snapshot={})
    protocol.pop("protocol_digest")
    # Recompute the canonical digest after shrinking the matrix for this unit test.
    import hashlib, json
    material = dict(protocol)
    protocol["protocol_digest"] = hashlib.sha256(json.dumps(
        material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    arms = {arm for _, arm, base in module.CONTRASTS for arm in (arm, base)}
    cells = []
    for block in protocol["primary_blocks"]:
        for seed in protocol["optimizer_seeds"]:
            for index, arm in enumerate(sorted(arms)):
                cells.append({
                    "manifest": {
                        "platform": block["platform"], "design": block["design"],
                        "optimizer_seed": seed, "arm": arm,
                        "frozen_study_protocol_digest": protocol["protocol_digest"],
                    },
                    "anytime_hypervolume": {"normalized_auc": float(index + 1)},
                    "baseline_improvement": {
                        "first_feasible_baseline_improving_round": 50 + index,
                    },
                    "baseline_summary": {
                        "replicas": 3, "successes": 3, "failure_rate": 0.0,
                        "metrics": {
                            "area_um2": {"count": 3, "median": 100.0,
                                         "minimum": 99.0, "maximum": 101.0,
                                         "q1": 99.5, "q3": 100.5, "iqr": 1.0},
                            "setup_wns_ns": {"count": 3, "median": 0.1,
                                             "minimum": 0.09, "maximum": 0.11,
                                             "q1": 0.095, "q3": 0.105, "iqr": 0.01},
                            "power_W": {"count": 3, "median": 0.01,
                                        "minimum": 0.009, "maximum": 0.011,
                                        "q1": 0.0095, "q3": 0.0105, "iqr": 0.001},
                        },
                        "constraints": [
                            {"metric": "setup_wns_ns", "operator": ">=",
                             "threshold": 0.0, "values": [0.09, 0.1, 0.11],
                             "passed": True},
                            {"metric": "drc_errors", "operator": "<=",
                             "threshold": 0.0, "values": [0.0, 0.0, 0.0],
                             "passed": True},
                        ],
                        "complete_objectives": True, "eligible": True,
                        # Identity must not affect scientific parity.
                        "run_ids": [f"{arm}-{seed}-a", f"{arm}-{seed}-b",
                                    f"{arm}-{seed}-c"],
                    },
                })
    result = module.analyze_native_aggregation(
        {"all_cells_eligible": True, "cells": cells,
         "study_id": protocol["study_id"],
         "protocol_digest": protocol["protocol_digest"]}, protocol)
    assert result["paired_unit_count"] == 6
    assert result["descriptive_seed_cell_count"] == 18
    assert len(result["contrasts"]) == 5
    assert len(result["co_primary_strong_control_tests"]) == 2
    assert all(row["analysis_role"] == "co_primary_strong_control"
               for row in result["co_primary_strong_control_tests"].values())
    assert result["empirical_baseline_improvement_attainment"]
    assert len(result["baseline_parity"]) == 6
    assert all(row["parity_verified"] for row in result["baseline_parity"].values())


def test_analysis_rejects_cross_arm_baseline_qor_drift():
    module = _module()
    cells = [
        {
            "manifest": {"platform": "asap7", "design": "ibex",
                         "optimizer_seed": seed, "arm": arm},
            "baseline_summary": {
                "replicas": 3, "successes": 3, "failure_rate": 0.0,
                "metrics": {"area_um2": {"count": 3, "median": area}},
                "constraints": [{"metric": "drc_errors", "operator": "<=",
                                 "threshold": 0.0, "values": [0.0] * 3,
                                 "passed": True}],
                "complete_objectives": True, "eligible": True,
                "run_ids": [f"{arm}-{seed}-{index}" for index in range(3)],
            },
        }
        for seed, arm, area in ((1103, "random", 100.0),
                                (1103, "qlognehvi", 101.0))
    ]
    import pytest
    with pytest.raises(ValueError, match="baseline QoR drift"):
        module._validate_baseline_parity(cells)


def test_analysis_rejects_cross_protocol_aggregation_before_statistics():
    module = _module()
    import json
    protocol = json.loads((Path(__file__).resolve().parents[1] /
        "studies/protocols/v2-industrial-dse-20260829-r27.protocol.json"
    ).read_text(encoding="utf-8"))
    import pytest
    with pytest.raises(ValueError, match="native aggregation protocol binding"):
        module.analyze_native_aggregation({
            "all_cells_eligible": True, "study_id": "study-old",
            "protocol_digest": "old", "cells": [],
        }, protocol)


def test_official_endpoint_requires_binding_and_keeps_failed_budget_rounds():
    module = _module()
    import json
    protocol = json.loads((Path(__file__).resolve().parents[1] /
        "studies/protocols/v2-industrial-dse-20260829-r27.protocol.json"
    ).read_text(encoding="utf-8"))
    baseline = {
        "eligible": True, "complete_objectives": True,
        "replicas": 3, "successes": 3,
        "metrics": {
            "setup_wns_ns": {"median": 0.1},
            "area_um2": {"median": 100.0},
            "power_W": {"median": 0.01},
        },
    }
    official = {
        "all_cells_eligible": True,
        "study_id": protocol["study_id"],
        "protocol_digest": protocol["protocol_digest"],
        "cells": [{
            "binding": {"platform": "asap7", "design": "aes",
                        "optimizer_seed": 1103},
            "logical_budget": 600,
            "trials": [
                {"logical_round": 1, "trial_id": "failed", "eligible": False,
                 "summary_metrics": None},
                {"logical_round": 2, "trial_id": "good", "eligible": True,
                 "summary_metrics": {"setup_wns_ns": 0.11,
                                     "area_um2": 99.0, "power_W": 0.009}},
                *({"logical_round": index, "trial_id": f"failed-{index}",
                   "eligible": False, "summary_metrics": None}
                  for index in range(3, 601)),
            ],
        }],
    }
    values, improvements = module._official_endpoint_values(
        official, protocol, {("asap7", "aes", 1103): baseline})
    key = ("asap7", "aes", 1103, "official_autotuner_hyperopt")
    assert values[key] > 0
    assert improvements[key] == 2
    official["protocol_digest"] = "stale"
    import pytest
    with pytest.raises(ValueError, match="official aggregation protocol binding"):
        module._official_endpoint_values(
            official, protocol, {("asap7", "aes", 1103): baseline})
