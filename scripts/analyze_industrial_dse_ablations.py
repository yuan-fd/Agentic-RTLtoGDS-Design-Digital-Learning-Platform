#!/usr/bin/env python3
"""Paired, equal-budget analysis of preregistered portfolio ablations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median
import sys


ROOT = Path(__file__).resolve().parents[1]
for source in (ROOT, *sorted((ROOT / "packages").glob("*/src"))):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from openroad_platform_analysis import (  # noqa: E402
    cliffs_delta, holm_adjust, paired_bootstrap_interval,
    paired_permutation_test, validate_industrial_dse_protocol,
)


def analyze_ablations(primary: dict, ablations: dict, protocol: dict) -> dict:
    validate_industrial_dse_protocol(protocol)
    if primary.get("all_cells_eligible") is not True:
        raise ValueError("primary aggregation is incomplete or ineligible")
    if ablations.get("all_cells_eligible") is not True:
        raise ValueError("ablation aggregation is incomplete or ineligible")
    budget = int(protocol["ablation_budget"])
    baseline = {}
    baseline_cost = {}
    for cell in primary.get("cells") or []:
        manifest = cell.get("manifest") or {}
        if manifest.get("frozen_study_protocol_digest") != protocol["protocol_digest"]:
            raise ValueError("primary protocol digest mismatch")
        if manifest.get("arm") != "portfolio" or manifest.get("ablation", "none") != "none":
            continue
        key = (manifest["platform"], manifest["design"], int(manifest["optimizer_seed"]))
        value = cell.get("anytime_hypervolume", {}).get(
            "checkpoint_normalized_auc", {}).get(str(budget))
        if value is None:
            raise ValueError("primary portfolio lacks the ablation-budget AUC checkpoint")
        baseline[key] = float(value)
        cost_record = cell.get("runtime_cost") or {}
        cost = cost_record.get("total_run_wall_seconds")
        if (not isinstance(cost, (int, float)) or float(cost) <= 0
                or cost_record.get("missing_duration_count", 0) != 0):
            raise ValueError("primary portfolio lacks positive additive Runtime cost")
        baseline_cost[key] = float(cost)
    registered = {item["ablation_id"] for item in protocol["ablations"]}
    observed = {}
    observed_cost = {}
    for cell in ablations.get("cells") or []:
        manifest = cell.get("manifest") or {}
        if manifest.get("frozen_study_protocol_digest") != protocol["protocol_digest"]:
            raise ValueError("ablation protocol digest mismatch")
        ablation_id = manifest.get("ablation")
        if ablation_id not in registered:
            raise ValueError(f"unregistered ablation cell: {ablation_id}")
        if int(cell.get("logical_budget") or 0) != budget:
            raise ValueError("ablation cell does not use the equal frozen budget")
        key = (manifest["platform"], manifest["design"],
               int(manifest["optimizer_seed"]), ablation_id)
        if key in observed:
            raise ValueError(f"duplicate ablation cell: {key}")
        observed[key] = float(cell["anytime_hypervolume"]["normalized_auc"])
        cost_record = cell.get("runtime_cost") or {}
        cost = cost_record.get("total_run_wall_seconds")
        if (not isinstance(cost, (int, float)) or float(cost) <= 0
                or cost_record.get("missing_duration_count", 0) != 0):
            raise ValueError("ablation cell lacks positive additive Runtime cost")
        observed_cost[key] = float(cost)
    blocks = [(block["platform"], block["design"])
              for block in protocol["primary_blocks"]]
    seed_units = [(*block, int(seed)) for block in blocks
                  for seed in protocol["optimizer_seeds"]]
    tests, primary_raw_p = {}, {}
    primary_ids = set((protocol.get("statistics") or {}).get(
        "ablation_co_primary_ids") or ())
    if primary_ids != {"no_gp", "no_memory", "no_edair"}:
        raise ValueError("frozen co-primary ablation family is missing")
    for ablation_id in sorted(registered - {"single_replica_error_control"}):
        full, removed, seed_level = [], [], []
        for platform, design in blocks:
            full_seeds, removed_seeds = [], []
            for seed in protocol["optimizer_seeds"]:
                unit = (platform, design, int(seed))
                if unit not in baseline or (*unit, ablation_id) not in observed:
                    raise ValueError(f"missing paired ablation unit: {unit}/{ablation_id}")
                full_seeds.append(baseline[unit])
                removed_seeds.append(observed[(*unit, ablation_id)])
                seed_level.append({
                    "platform": platform, "design": design,
                    "optimizer_seed": seed, "full": baseline[unit],
                    "ablation": observed[(*unit, ablation_id)],
                    "difference": baseline[unit] - observed[(*unit, ablation_id)],
                })
            full.append(float(median(full_seeds)))
            removed.append(float(median(removed_seeds)))
        differences = [left - right for left, right in zip(full, removed)]
        permutation = paired_permutation_test(
            differences, alternative="greater",
            seed_material=f"{protocol['protocol_digest']}:{ablation_id}")
        analysis_role = ("co_primary_mechanism" if ablation_id in primary_ids
                         else "secondary_mechanism_estimate")
        if ablation_id in primary_ids:
            primary_raw_p[ablation_id] = permutation["p_value"]
        tests[ablation_id] = {
            "analysis_role": analysis_role,
            "interpretation": "positive difference supports the removed component",
            "paired_unit_count": len(blocks),
            "paired_unit": "design-PDK block after median over optimizer seeds",
            "descriptive_seed_cell_count": len(seed_level),
            "seed_level_descriptive_cells": seed_level,
            "full_portfolio_values": full,
            "ablation_values": removed, "paired_differences": differences,
            "permutation": permutation,
            "paired_bootstrap": paired_bootstrap_interval(
                differences, samples=10_000,
                seed_material=f"{protocol['protocol_digest']}:{ablation_id}:bootstrap"),
            "cliffs_delta_unpaired_descriptive": cliffs_delta(full, removed),
        }
    adjusted = holm_adjust(primary_raw_p)
    for name, value in adjusted.items():
        tests[name]["holm_adjusted_p_value"] = value
        tests[name]["reject_at_familywise_0_05"] = value <= .05
    error_control = []
    for unit in seed_units:
        key = (*unit, "single_replica_error_control")
        if unit not in baseline or key not in observed:
            raise ValueError(f"missing single-replica error-control unit: {unit}")
        error_control.append({
            "platform": unit[0], "design": unit[1], "optimizer_seed": unit[2],
            "replicated_auc": baseline[unit], "single_replica_auc": observed[key],
            "difference": observed[key] - baseline[unit],
        })
    multifidelity_rows, multifidelity_block_savings = [], []
    for platform, design in blocks:
        full_costs, removed_costs = [], []
        for seed in protocol["optimizer_seeds"]:
            unit = (platform, design, int(seed))
            removed_key = (*unit, "no_multifidelity")
            full_cost = baseline_cost[unit]
            removed_cost = observed_cost[removed_key]
            full_costs.append(full_cost); removed_costs.append(removed_cost)
            multifidelity_rows.append({
                "platform": platform, "design": design,
                "optimizer_seed": seed,
                "multifidelity_run_wall_seconds": full_cost,
                "no_multifidelity_run_wall_seconds": removed_cost,
                "saved_fraction": 1.0 - full_cost / removed_cost,
            })
        full_median = float(median(full_costs))
        removed_median = float(median(removed_costs))
        multifidelity_block_savings.append(1.0 - full_median / removed_median)
    return {
        "schema_version": 1, "kind": "industrial-dse-paired-ablation-statistics",
        "study_id": protocol["study_id"], "protocol_digest": protocol["protocol_digest"],
        "equal_budget": budget, "paired_unit_count": len(blocks),
        "paired_unit": "design-PDK block after median over optimizer seeds",
        "descriptive_seed_cell_count": len(seed_units),
        "mechanism_ablations": tests,
        "co_primary_ablation_family": sorted(primary_ids),
        "secondary_ablation_claim_boundary": (
            "Secondary mechanisms retain paired effects and unadjusted exact p-values "
            "for transparency but do not support confirmatory significance claims. "
            "The no_multifidelity arm is interpreted jointly with runtime/compute cost."
        ),
        "multifidelity_efficiency": {
            "paired_unit": "design-PDK block after median over optimizer seeds",
            "paired_unit_count": len(blocks),
            "seed_level_descriptive_cells": multifidelity_rows,
            "block_saved_fractions": multifidelity_block_savings,
            "median_saved_fraction": float(median(multifidelity_block_savings)),
            "paired_bootstrap": paired_bootstrap_interval(
                multifidelity_block_savings, samples=10_000,
                seed_material=f"{protocol['protocol_digest']}:multifidelity-cost"),
            "positive_means": (
                "the full portfolio consumed fewer additive Runtime run-wall seconds "
                "than the equal-budget no_multifidelity arm"),
            "claim_boundary": (
                "Additive per-run wall time measures compute work across parallel workers; "
                "QoR AUC remains separately reported and neither endpoint substitutes for the other."),
        },
        "single_replica_error_control": {
            "rows": error_control,
            "claim_boundary": (
                "Descriptive over/under-estimation diagnostic only; it is not a QoR "
                "component ablation and is excluded from mechanism significance tests."),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--primary-aggregation", type=Path, required=True)
    parser.add_argument("--ablation-aggregation", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=
                        ROOT / "studies/protocols/v2-industrial-dse-20260829-r27.protocol.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    primary = json.loads(args.primary_aggregation.expanduser().resolve().read_text())
    ablations = json.loads(args.ablation_aggregation.expanduser().resolve().read_text())
    protocol = json.loads(args.protocol.expanduser().resolve().read_text())
    result = analyze_ablations(primary, ablations, protocol)
    output = args.output.expanduser().resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(output)
    print(json.dumps({"output": str(output),
                      "ablations": len(result["mechanism_ablations"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
