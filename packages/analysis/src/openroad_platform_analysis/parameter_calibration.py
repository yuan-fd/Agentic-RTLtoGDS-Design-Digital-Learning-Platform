"""Aggregate controlled ORFS parameter-liveness experiments.

This module deliberately separates *mechanical liveness* from QoR causality.
Seeing a value in an OpenROAD command is strong evidence that the knob reached
its consumer.  Different ODB hashes or metrics under a one-factor perturbation
are useful corroboration, but are never labelled a causal QoR improvement.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_calibration_evaluation(case: Mapping[str, Any]) -> dict[str, Any]:
    workdir = Path(str(case["workdir"]))
    result_path = workdir / "run_result.json"
    liveness_path = workdir / "analysis/parameter_liveness.json"
    metrics_path = workdir / "analysis/stage_metrics.json"
    result = json.loads(result_path.read_text()) if result_path.is_file() else {}
    liveness = json.loads(liveness_path.read_text()) if liveness_path.is_file() else {}
    metrics = json.loads(metrics_path.read_text()) if metrics_path.is_file() else {}
    target_row = next(
        (row for row in liveness.get("parameters", [])
         if row.get("name") == case["parameter"]),
        {},
    )
    stage_prefix = {"floorplan": "2_floorplan.odb", "place": "3_place.odb",
                    "cts": "4_cts.odb"}.get(case["target_stage"])
    odb = (workdir / "results" / case["platform"] / case["design"] / "base" /
           stage_prefix) if stage_prefix else Path("/__missing__")
    stage_metrics = ((metrics.get("stages") or {}).get(case["target_stage"]) or {}).get(
        "metrics", {}
    )
    return {
        **dict(case),
        "run_status": result.get("status", "missing"),
        "evidence_level": target_row.get("evidence_level", "missing"),
        "runtime_observed": bool(target_row.get("runtime_observed")),
        "materialized_match": bool(target_row.get("materialized_match")),
        "consumer_declared": bool(target_row.get("consumer_declared")),
        "consumer_stage_completed": bool(target_row.get("stage_completed")),
        "liveness_rule_version": liveness.get("liveness_rule_version"),
        "target_odb_sha256": _sha256(odb),
        "target_stage_metrics": stage_metrics,
        "evidence_path": str(liveness_path),
    }


def _metric_signature(metrics: Mapping[str, Any]) -> str:
    numeric = {key: value for key, value in metrics.items()
               if isinstance(value, (int, float)) and not isinstance(value, bool)}
    return hashlib.sha256(json.dumps(numeric, sort_keys=True).encode()).hexdigest()


def aggregate_parameter_calibration(cases: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    evaluations = [read_calibration_evaluation(case) for case in cases]
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in evaluations:
        grouped[(row["platform"], row["parameter"])].append(row)

    summaries = []
    for (platform, parameter), rows in sorted(grouped.items()):
        levels = sorted({json.dumps(row["requested_value"], sort_keys=True) for row in rows})
        successful = [row for row in rows if row["run_status"] == "succeeded"]
        observed_levels = {json.dumps(row["requested_value"], sort_keys=True)
                           for row in successful if row["runtime_observed"]}
        all_materialized = len(successful) == len(rows) and all(
            row["materialized_match"] for row in successful)
        all_consumed = bool(successful) and all(
            row["consumer_declared"] and row["consumer_stage_completed"]
            for row in successful)

        by_seed: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in successful:
            by_seed[int(row["or_seed"])].append(row)
        odb_divergent_seeds = 0
        metric_divergent_seeds = 0
        for seed_rows in by_seed.values():
            if len({row["target_odb_sha256"] for row in seed_rows
                    if row["target_odb_sha256"]}) >= 2:
                odb_divergent_seeds += 1
            if len({_metric_signature(row["target_stage_metrics"]) for row in seed_rows}) >= 2:
                metric_divergent_seeds += 1

        requested_values = {row["requested_value"] for row in rows}
        switch_verified = (
            requested_values == {0, 1}
            and any(row["requested_value"] == 1 and row["runtime_observed"]
                    for row in successful)
            and all(not row["runtime_observed"] for row in successful
                    if row["requested_value"] == 0)
            and all_materialized and all_consumed
        )
        if not all_materialized or not all_consumed:
            classification = "inconsistent"
            eligible = False
        elif len(observed_levels) >= min(2, len(levels)):
            classification = "runtime_value_verified"
            eligible = True
        elif switch_verified:
            classification = "runtime_switch_verified"
            eligible = True
        elif odb_divergent_seeds >= 2 and metric_divergent_seeds >= 2:
            classification = "consumer_and_behavior_verified"
            eligible = True
        else:
            classification = "unresolved"
            eligible = False
        summaries.append({
            "platform": platform,
            "parameter": parameter,
            "classification": classification,
            "search_eligible": eligible,
            "planned_runs": len(rows),
            "successful_runs": len(successful),
            "levels": [json.loads(value) for value in levels],
            "runtime_observed_levels": [json.loads(value) for value in sorted(observed_levels)],
            "odb_divergent_paired_seeds": odb_divergent_seeds,
            "metric_divergent_paired_seeds": metric_divergent_seeds,
            "claim_boundary": (
                "Liveness only. Output/metric divergence corroborates that a controlled "
                "perturbation propagated; it is not proof of a beneficial causal QoR effect."
            ),
        })

    return {
        "schema_version": 1,
        "protocol": "single-knob-low-mid-high-three-paired-seeds-v1",
        "evaluation_count": len(evaluations),
        "parameters": summaries,
        "excluded_from_search": [
            {"platform": row["platform"], "parameter": row["parameter"],
             "reason": row["classification"]}
            for row in summaries if not row["search_eligible"]
        ],
        "evaluations": evaluations,
        "claim_boundary": (
            "This report validates parameter transport and consumer behavior only; "
            "optimizer superiority requires separate repeated full-flow experiments."
        ),
    }

