#!/usr/bin/env python3
"""Preregistered paired statistics over evidence-gated native DSE cells."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from statistics import median
import sys


ROOT = Path(__file__).resolve().parents[1]
for source in (ROOT, *sorted((ROOT / "packages").glob("*/src"))):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from openroad_platform_analysis import (  # noqa: E402
    anytime_hypervolume_summary, baseline_improvement_summary, cliffs_delta,
    empirical_attainment_summary, holm_adjust, relative_utility,
    observed_hypervolume_trace, paired_bootstrap_interval,
    paired_permutation_test, validate_industrial_dse_protocol,
)
from openroad_platform_contracts import ObjectiveSpec  # noqa: E402


CONTRASTS = (
    ("common_qlognehvi_vs_random", "qlognehvi", "random"),
    ("common_qlognehvi_vs_sobol", "qlognehvi", "sobol"),
    ("common_qlognehvi_vs_tpe", "qlognehvi", "tpe"),
    ("full_portfolio_vs_random", "portfolio", "random_full"),
    ("full_portfolio_vs_sobol", "portfolio", "sobol_full"),
)


def _baseline_content_payload(summary: dict) -> dict:
    """Return only scientific baseline evidence, excluding execution identity.

    Baselines are rerun in every optimizer cell.  Those reruns must describe the
    same physical reference before per-cell normalization is allowed.  Runtime
    run IDs and scheduling metadata are deliberately excluded; replicated QoR,
    feasibility, and eligibility are deliberately retained.
    """
    if not isinstance(summary, dict):
        raise ValueError("native cell lacks a baseline summary")
    metrics = summary.get("metrics")
    constraints = summary.get("constraints")
    if not isinstance(metrics, dict) or not isinstance(constraints, list):
        raise ValueError("native baseline summary lacks metrics or constraints")
    return {
        "replicas": summary.get("replicas"),
        "successes": summary.get("successes"),
        "failure_rate": summary.get("failure_rate"),
        "metrics": metrics,
        "constraints": constraints,
        "complete_objectives": summary.get("complete_objectives"),
        "eligible": summary.get("eligible"),
    }


def _baseline_content_fingerprint(summary: dict) -> str:
    payload = _baseline_content_payload(summary)
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_baseline_parity(cells: list[dict]) -> dict:
    """Reject cross-arm baseline drift within every design-PDK block."""
    by_block: dict[tuple[str, str], list[dict]] = {}
    for cell in cells:
        manifest = cell.get("manifest") or {}
        block = (manifest.get("platform"), manifest.get("design"))
        if not all(isinstance(item, str) and item for item in block):
            raise ValueError("native cell lacks platform/design baseline binding")
        fingerprint = _baseline_content_fingerprint(cell.get("baseline_summary"))
        by_block.setdefault(block, []).append({
            "arm": manifest.get("arm"),
            "optimizer_seed": int(manifest.get("optimizer_seed")),
            "fingerprint": fingerprint,
        })
    report = {}
    for (platform, design), rows in sorted(by_block.items()):
        fingerprints = sorted({row["fingerprint"] for row in rows})
        if len(fingerprints) != 1:
            examples = sorted(rows, key=lambda row: (
                str(row["arm"]), row["optimizer_seed"], row["fingerprint"]))
            raise ValueError(
                "baseline QoR drift across paired native cells for "
                f"{platform}/{design}: {examples[:6]}"
            )
        report[f"{platform}/{design}"] = {
            "content_fingerprint": fingerprints[0],
            "cell_count": len(rows),
            "parity_verified": True,
        }
    return report


def _paired_block_values(values: dict, protocol: dict, *, candidate_arm: str,
                         baseline_arms: tuple[str, ...]) -> dict:
    """Aggregate optimizer seeds inside each preregistered design-PDK block.

    With more than one baseline arm, the baseline is the best observed arm in
    each optimizer-seed cell.  This is deliberately conservative: the
    candidate must beat an oracle-selected strong control, not merely Random.
    """
    candidate_values, baseline_values, differences, seed_level = [], [], [], []
    missing = []
    for block in protocol["primary_blocks"]:
        platform, design = block["platform"], block["design"]
        block_candidates, block_baselines = [], []
        for seed in protocol["optimizer_seeds"]:
            candidate_key = (platform, design, int(seed), candidate_arm)
            baseline_keys = [
                (platform, design, int(seed), arm) for arm in baseline_arms
            ]
            if candidate_key not in values or any(key not in values for key in baseline_keys):
                missing.append({"candidate": candidate_key,
                                "baselines": baseline_keys})
                continue
            candidate = values[candidate_key]
            components = {key[3]: values[key] for key in baseline_keys}
            baseline = max(components.values())
            block_candidates.append(candidate); block_baselines.append(baseline)
            seed_level.append({
                "platform": platform, "design": design, "optimizer_seed": seed,
                "candidate": candidate, "baseline": baseline,
                "baseline_components": components,
                "difference": candidate - baseline,
            })
        if len(block_candidates) == len(protocol["optimizer_seeds"]):
            candidate = float(median(block_candidates))
            baseline = float(median(block_baselines))
            candidate_values.append(candidate); baseline_values.append(baseline)
            differences.append(candidate - baseline)
    if missing:
        raise ValueError(
            f"candidate {candidate_arm} has missing paired cells: {missing[:3]}")
    return {
        "candidate_values": candidate_values,
        "baseline_values": baseline_values,
        "paired_differences": differences,
        "seed_level_descriptive_cells": seed_level,
    }


def _paired_effect_report(rows: dict, *, protocol: dict, name: str) -> dict:
    differences = rows["paired_differences"]
    wins = sum(value > 0 for value in differences)
    ties = sum(value == 0 for value in differences)
    losses = sum(value < 0 for value in differences)
    return {
        **rows,
        "paired_unit_count": len(differences),
        "paired_unit": "design-PDK block after median over optimizer seeds",
        "permutation": paired_permutation_test(
            differences, alternative="greater",
            seed_material=f"{protocol['protocol_digest']}:{name}",
            unit="one design-PDK block after median across optimizer seeds"),
        "paired_bootstrap": paired_bootstrap_interval(
            differences, samples=10_000,
            seed_material=f"{protocol['protocol_digest']}:{name}:bootstrap"),
        "paired_win_tie_loss": {"wins": wins, "ties": ties, "losses": losses},
        # Cliff's delta ignores pairing, so it is descriptive only.  The exact
        # paired sign-flip test above remains the preregistered inference.
        "cliffs_delta_unpaired_descriptive": cliffs_delta(
            rows["candidate_values"], rows["baseline_values"]),
    }


def _official_endpoint_values(official: dict, protocol: dict,
                              native_baselines: dict) -> tuple[dict, dict]:
    if official.get("all_cells_eligible") is not True:
        raise ValueError("all official AutoTuner cells must pass evidence aggregation")
    if (official.get("protocol_digest") != protocol["protocol_digest"]
            or official.get("study_id") != protocol["study_id"]):
        raise ValueError("official aggregation protocol binding mismatch")
    objectives = tuple(ObjectiveSpec(
        item["metric"], item["direction"], item["weight"],
        1.0 if item["metric"] == "setup_wns_ns" else None,
    ) for item in protocol["objectives"])
    values, improvements = {}, {}
    for cell in official.get("cells") or []:
        binding = cell.get("binding") or {}
        key3 = (binding.get("platform"), binding.get("design"),
                int(binding.get("optimizer_seed")))
        baseline = native_baselines.get(key3)
        if baseline is None:
            raise ValueError(f"official cell has no paired native baseline: {key3}")
        history = []
        for trial in cell.get("trials") or []:
            summary_metrics = trial.get("summary_metrics")
            summary = ({
                "eligible": True,
                "metrics": {name: {"median": value}
                            for name, value in summary_metrics.items()},
            } if trial.get("eligible") and summary_metrics else {
                "eligible": False, "metrics": {},
            })
            history.append({
                "kind": "bo_candidate", "round": trial["logical_round"],
                "candidate_id": trial.get("trial_id"),
                "summary": summary,
                "utility": (relative_utility(summary, baseline, objectives)
                            if summary["eligible"] else None),
            })
        trace = observed_hypervolume_trace(history, objectives, baseline)
        arm_key = (*key3, "official_autotuner_hyperopt")
        values[arm_key] = float(
            anytime_hypervolume_summary(
                trace, budget=int(cell["logical_budget"]))["normalized_auc"])
        improvements[arm_key] = baseline_improvement_summary(
            history, budget=int(cell["logical_budget"]),
            checkpoints=protocol["budget_checkpoints"],
        )["first_feasible_baseline_improving_round"]
    return values, improvements


def analyze_native_aggregation(aggregation: dict, protocol: dict,
                               official_aggregation: dict | None = None) -> dict:
    validate_industrial_dse_protocol(protocol)
    if aggregation.get("all_cells_eligible") is not True:
        raise ValueError("all native cells must pass evidence aggregation")
    if (aggregation.get("protocol_digest") != protocol["protocol_digest"]
            or aggregation.get("study_id") != protocol["study_id"]):
        raise ValueError("native aggregation protocol binding mismatch")
    cells = aggregation.get("cells") or []
    baseline_parity = _validate_baseline_parity(cells)
    values, improvements = {}, {}
    native_baselines = {}
    for cell in cells:
        manifest = cell.get("manifest") or {}
        if manifest.get("frozen_study_protocol_digest") != protocol["protocol_digest"]:
            raise ValueError("native cell protocol digest mismatch")
        key = (manifest.get("platform"), manifest.get("design"),
               int(manifest.get("optimizer_seed")), manifest.get("arm"))
        if key in values:
            raise ValueError(f"duplicate paired native cell: {key}")
        values[key] = float(cell["anytime_hypervolume"]["normalized_auc"])
        improvement = cell.get("baseline_improvement") or {}
        if "first_feasible_baseline_improving_round" not in improvement:
            raise ValueError(f"native cell lacks baseline-improvement endpoint: {key}")
        improvements[key] = improvement["first_feasible_baseline_improving_round"]
        if manifest.get("arm") == "random":
            native_baselines[key[:3]] = cell.get("baseline_summary")
    if official_aggregation is not None:
        official_values, official_improvements = _official_endpoint_values(
            official_aggregation, protocol, native_baselines)
        values.update(official_values)
        improvements.update(official_improvements)
    seed_cells = [
        (block["platform"], block["design"], int(seed))
        for block in protocol["primary_blocks"]
        for seed in protocol["optimizer_seeds"]
    ]
    paired_blocks = [
        (block["platform"], block["design"])
        for block in protocol["primary_blocks"]
    ]
    tests = {}
    raw_p = {}
    contrasts = list(CONTRASTS)
    if official_aggregation is not None:
        contrasts.append(("common_qlognehvi_vs_official_autotuner",
                          "qlognehvi", "official_autotuner_hyperopt"))
    for name, candidate_arm, baseline_arm in contrasts:
        rows = _paired_block_values(
            values, protocol, candidate_arm=candidate_arm,
            baseline_arms=(baseline_arm,))
        tests[name] = {
            "candidate_arm": candidate_arm, "baseline_arm": baseline_arm,
            "analysis_role": "secondary_pairwise",
            **_paired_effect_report(rows, protocol=protocol, name=name),
        }
        raw_p[name] = tests[name]["permutation"]["p_value"]
    adjusted = holm_adjust(raw_p)
    for name, value in adjusted.items():
        tests[name]["secondary_holm_adjusted_p_value"] = value
        tests[name]["secondary_reject_at_familywise_0_05"] = value <= .05

    primary_specs = [
        ("common_qlognehvi_vs_best_strong_control", "qlognehvi",
         ("random", "sobol", "tpe") + (
             ("official_autotuner_hyperopt",) if official_aggregation is not None else ())),
        ("full_portfolio_vs_best_equal_domain_control", "portfolio",
         ("random_full", "sobol_full")),
    ]
    primary_tests, primary_raw_p = {}, {}
    for name, candidate_arm, baseline_arms in primary_specs:
        rows = _paired_block_values(
            values, protocol, candidate_arm=candidate_arm,
            baseline_arms=baseline_arms)
        primary_tests[name] = {
            "candidate_arm": candidate_arm,
            "oracle_selected_baseline_arms": list(baseline_arms),
            "analysis_role": "co_primary_strong_control",
            "equal_budget_per_component_arm": True,
            "composite_baseline_total_compute_is_larger": len(baseline_arms) > 1,
            "complete_preregistered_control_set": (
                name != "common_qlognehvi_vs_best_strong_control"
                or official_aggregation is not None),
            **_paired_effect_report(rows, protocol=protocol, name=name),
        }
        primary_raw_p[name] = primary_tests[name]["permutation"]["p_value"]
    for name, value in holm_adjust(primary_raw_p).items():
        primary_tests[name]["holm_adjusted_p_value"] = value
        primary_tests[name]["reject_at_familywise_0_05"] = value <= .05
    attainment = {}
    for arm in sorted({key[3] for key in values}):
        rounds = [improvements[(platform, design, seed, arm)]
                  for platform, design, seed in seed_cells]
        attainment[arm] = empirical_attainment_summary(
            rounds, budget=max(protocol["budget_checkpoints"]),
            checkpoints=protocol["budget_checkpoints"],
        )
    return {
        "schema_version": 2,
        "kind": "industrial-dse-native-paired-statistics",
        "study_id": protocol["study_id"],
        "protocol_digest": protocol["protocol_digest"],
        "paired_unit": protocol["statistics"]["unit"],
        "paired_unit_count": len(paired_blocks),
        "descriptive_seed_cell_count": len(seed_cells),
        "metric": "normalized observed feasible hypervolume AUC",
        "co_primary_strong_control_tests": primary_tests,
        "secondary_pairwise_contrasts": tests,
        # Compatibility alias; every member is explicitly labelled secondary.
        "contrasts": tests,
        "empirical_baseline_improvement_attainment": attainment,
        "baseline_parity": baseline_parity,
        "claim_boundary": (
            "Common-domain and full-domain contrast families are never crossed. " +
            ("Official AutoTuner was included through its separate evidence adapter."
             if official_aggregation is not None else
             "Official AutoTuner requires its separate evidence adapter before inclusion; "
             "the common-domain co-primary claim is therefore incomplete.")),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aggregation", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=
                        ROOT / "studies/protocols/v2-industrial-dse-20260829-r27.protocol.json")
    parser.add_argument("--official-aggregation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    aggregation = json.loads(
        args.aggregation.expanduser().resolve().read_text(encoding="utf-8"))
    protocol = json.loads(
        args.protocol.expanduser().resolve().read_text(encoding="utf-8"))
    official = json.loads(args.official_aggregation.expanduser().resolve().read_text(
        encoding="utf-8"))
    result = analyze_native_aggregation(aggregation, protocol, official)
    output = args.output.expanduser().resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")
    temporary.replace(output)
    print(json.dumps({"output": str(output), "contrasts": len(result["contrasts"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
