#!/usr/bin/env python3
"""Evidence-gated aggregation for native industrial DSE campaign cells."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from datetime import datetime
import sys


ROOT = Path(__file__).resolve().parents[1]
for source in (ROOT, *sorted((ROOT / "packages").glob("*/src"))):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from openroad_platform_analysis import (  # noqa: E402
    anytime_hypervolume_summary, baseline_improvement_summary,
)
from openroad_platform_scheduler.local_state import (  # noqa: E402
    resolve_mirrored_database,
)


TERMINAL = {"completed", "diagnosis_required", "failed"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_digest(snapshot: dict) -> str:
    records = snapshot.get("files")
    if not isinstance(records, list) or snapshot.get("file_count") != len(records):
        return ""
    return hashlib.sha256(json.dumps(
        records, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


def _value_fingerprint(value: dict) -> str:
    return hashlib.sha256(json.dumps(
        {key: item for key, item in value.items() if key != "fingerprint"},
        sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


def _runtime_common_evaluations(cell: Path) -> dict:
    try:
        database = resolve_mirrored_database(cell, "runtime.db")
    except ValueError as exc:
        return {"run_count": 0, "evaluations": [], "errors": [str(exc)]}
    if not database.is_file():
        return {"run_count": 0, "evaluations": [], "errors": ["runtime.db missing"]}
    rows, errors = [], []
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        runs = list(connection.execute(
            "SELECT run_id, status, task_spec_json FROM runtime_runs ORDER BY created_at"))
        for run in runs:
            task = json.loads(run["task_spec_json"])
            if task.get("parameters", {}).get("target_stage") != "finish":
                continue
            artifact = connection.execute(
                """SELECT artifact.store_key, artifact.size_bytes, artifact.sha256,
                          attempt.workspace
                   FROM runtime_artifacts artifact
                   JOIN runtime_attempts attempt
                     ON attempt.attempt_id=artifact.attempt_id
                   JOIN runtime_stage_runs stage
                     ON stage.stage_run_id=attempt.stage_run_id
                   WHERE stage.run_id=?
                     AND artifact.store_key LIKE '%common_evaluation.json'
                   ORDER BY artifact.created_at DESC LIMIT 1""",
                (run["run_id"],)).fetchone()
            row = {
                "run_id": run["run_id"], "runtime_status": run["status"],
                "or_seed": task.get("parameters", {}).get("or_seed"),
                "fidelity": task.get("labels", {}).get("fidelity"),
                "candidate_id": task.get("labels", {}).get(
                    "optimizer_candidate_id"),
                "replica_index": task.get("labels", {}).get("replica_index"),
            }
            if run["status"] != "succeeded":
                row["evaluation_status"] = "not_required_for_failed_runtime"
                rows.append(row); continue
            if artifact is None:
                errors.append(f"{run['run_id']}: successful finish run lacks common evaluation")
                row["evaluation_status"] = "missing"; rows.append(row); continue
            path = (Path(artifact["workspace"]) / artifact["store_key"]).resolve()
            if (not path.is_file() or path.stat().st_size != artifact["size_bytes"]
                    or _sha256(path) != artifact["sha256"]):
                errors.append(f"{run['run_id']}: common evaluation artifact integrity failure")
                row["evaluation_status"] = "integrity_failure"; rows.append(row); continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            if (payload.get("schema_version") != 3
                    or payload.get("kind") != "common-orfs-signoff-evaluation"
                    or payload.get("normalized_stage_evidence", {}).get(
                        "units", {}).get("time", {}).get("status") != "verified"):
                errors.append(f"{run['run_id']}: unsupported or unit-unverified evaluator")
                row["evaluation_status"] = "schema_failure"; rows.append(row); continue
            runtime_seconds = (payload.get("metrics") or {}).get("runtime_seconds")
            if (isinstance(runtime_seconds, bool)
                    or not isinstance(runtime_seconds, (int, float))
                    or not math.isfinite(float(runtime_seconds))
                    or float(runtime_seconds) <= 0):
                errors.append(f"{run['run_id']}: missing positive wall-time evidence")
                row["evaluation_status"] = "runtime_evidence_failure"
                rows.append(row); continue
            row.update({
                "evaluation_status": "verified", "evaluation_id": payload["evaluation_id"],
                "feasible": payload["feasible"], "metrics": payload["metrics"],
                "artifact_sha256": artifact["sha256"],
            })
            rows.append(row)
    return {"run_count": len(runs), "evaluations": rows, "errors": errors}


def _runtime_cost_summary(cell: Path) -> dict:
    """Sum terminal run wall time across quick/full workers without double counting."""
    try:
        database = resolve_mirrored_database(cell, "runtime.db")
    except ValueError as exc:
        return {"errors": [str(exc)], "runs": []}
    if not database.is_file():
        return {"errors": ["runtime.db missing"], "runs": []}
    rows, errors = [], []
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        records = list(connection.execute(
            "SELECT run_id, status, task_spec_json, started_at, ended_at "
            "FROM runtime_runs ORDER BY created_at"))
    for record in records:
        task = json.loads(record["task_spec_json"])
        started, ended = record["started_at"], record["ended_at"]
        duration = None
        duration_status = "missing"
        if started and ended:
            try:
                duration = (datetime.fromisoformat(ended)
                            - datetime.fromisoformat(started)).total_seconds()
            except ValueError:
                duration = None
            if duration is not None and math.isfinite(duration) and duration > 0:
                duration_status = "verified"
        elif not started and not ended and record["status"] in {"cancelled", "failed"}:
            # A budgeted proposal may be cancelled before a worker starts it.
            # Its run-wall compute cost is exactly zero, not missing evidence.
            duration = 0.0
            duration_status = "verified_unstarted_zero_compute"
        if duration_status == "missing":
            errors.append(f"{record['run_id']}: terminal wall-time evidence missing")
        rows.append({
            "run_id": record["run_id"], "status": record["status"],
            "target_stage": task.get("parameters", {}).get("target_stage"),
            "fidelity": task.get("labels", {}).get("fidelity"),
            "duration_seconds": duration,
            "duration_status": duration_status,
        })
    valid = [row for row in rows if row["duration_status"].startswith("verified")]
    by_stage = {}
    for row in valid:
        stage = str(row.get("target_stage") or "unknown")
        bucket = by_stage.setdefault(stage, {"run_count": 0, "run_wall_seconds": 0.0})
        bucket["run_count"] += 1
        bucket["run_wall_seconds"] += float(row["duration_seconds"])
    return {
        "run_count": len(rows), "runs": rows,
        "verified_duration_count": len(valid),
        "missing_duration_count": len(rows) - len(valid),
        "total_run_wall_seconds": float(sum(row["duration_seconds"] for row in valid)),
        "by_target_stage": by_stage,
        "errors": errors,
        "unit": "sum of per-Run Runtime wall seconds; parallel workers remain additive",
    }


def aggregate_cell(cell: Path, *, protocol_digest: str,
                   budget_checkpoints: tuple[int, ...] = (),
                   campaign_controller_source_sha256: str | None = None,
                   expected_reference_fingerprint: str | None = None,
                   campaign_python_environment_sha256: str | None = None) -> dict:
    errors = []
    if (cell / "EXCLUDED_FROM_FORMAL_STUDY.json").exists():
        errors.append("cell is explicitly excluded from the formal study")
    for name in ("cell-manifest.json", "controller-source-snapshot.json",
                 "python-environment.json",
                 "checkpoint-export.json"):
        if not (cell / name).is_file():
            errors.append(f"{name} missing")
    if errors:
        return {"cell": cell.name, "eligible": False, "errors": errors}
    manifest = json.loads((cell / "cell-manifest.json").read_text(encoding="utf-8"))
    source = json.loads((cell / "controller-source-snapshot.json").read_text(encoding="utf-8"))
    python_environment = json.loads(
        (cell / "python-environment.json").read_text(encoding="utf-8"))
    checkpoint = json.loads((cell / "checkpoint-export.json").read_text(encoding="utf-8"))
    state = checkpoint["state"]
    if manifest.get("frozen_study_protocol_digest") != protocol_digest:
        errors.append("frozen study protocol digest mismatch")
    if manifest.get("study_mode") != "paper":
        errors.append("native cell was not executed in paper mode")
    if (expected_reference_fingerprint is not None
            and manifest.get("reference_design_fingerprint") !=
            expected_reference_fingerprint):
        errors.append("native reference design differs from the frozen source bundle")
    if manifest.get("common_evaluator_schema") != 3:
        errors.append("common evaluator schema is not 3")
    if manifest.get("toolchain_validated") is not True:
        errors.append("cell did not use a validated pinned toolchain")
    toolchain_path = cell / "toolchain-validation.json"
    if not toolchain_path.is_file():
        errors.append("toolchain-validation.json missing")
    else:
        toolchain = json.loads(toolchain_path.read_text(encoding="utf-8"))
        if (toolchain.get("validated") is not True
                or toolchain.get("validation_fingerprint") !=
                manifest.get("toolchain_validation_fingerprint")
                or toolchain.get("lock_sha256") !=
                manifest.get("toolchain_lock_sha256")):
            errors.append("toolchain validation evidence mismatch")
    if (_snapshot_digest(source) != source.get("digest")
            or manifest.get("controller_source_snapshot_sha256") != source.get("digest")):
        errors.append("controller source snapshot digest mismatch")
    if (campaign_controller_source_sha256 is not None
            and source.get("digest") != campaign_controller_source_sha256):
        errors.append("cell controller source differs from the frozen campaign snapshot")
    if (_value_fingerprint(python_environment) !=
            python_environment.get("fingerprint")
            or manifest.get("python_environment_fingerprint") !=
                python_environment.get("fingerprint")
            or (campaign_python_environment_sha256 is not None
                and python_environment.get("fingerprint") !=
                campaign_python_environment_sha256)):
        errors.append("cell Python optimization environment differs from campaign")
    if state.get("status") not in TERMINAL:
        errors.append("cell is not terminal")
    if state.get("status") == "failed":
        errors.append("controller/protocol failure is not an optimizer outcome")
    if manifest.get("ablation", "none") != state.get("ablation_id", "none"):
        errors.append("cell manifest and checkpoint ablation mismatch")
    if state.get("status") in {"completed", "diagnosis_required"} and (
            state.get("round") != state.get("max_rounds")):
        errors.append("algorithmic cell terminated before its fixed budget")
    evidence = _runtime_common_evaluations(cell)
    errors.extend(evidence["errors"])
    runtime_cost = _runtime_cost_summary(cell)
    history = state.get("history") or []
    full = [item for item in history if item.get("kind") in {"baseline", "bo_candidate"}]
    baseline_rows = [item for item in full if item.get("kind") == "baseline"]
    if len(baseline_rows) != 1:
        errors.append("cell must contain exactly one repeated baseline summary")
    quick_only = [item for item in history if item.get("kind") == "quick_proxy_only"]
    candidate_rows = [item for item in history
                      if item.get("kind") in {"bo_candidate", "quick_proxy_only"}]
    if len(candidate_rows) != int(state.get("max_rounds") or 0):
        errors.append("logical proposal ledger does not match the fixed budget")
    feasible = [item for item in full
                if (item.get("summary") or {}).get("eligible") is True]
    best = max((item for item in feasible if isinstance(item.get("utility"), (int, float))),
               key=lambda item: float(item["utility"]), default=None)
    expected_replicas = int(state.get("repetitions") or 0)
    expected_seeds = list(state.get("replica_or_seeds") or [])
    all_summary_run_ids = []
    for item in full:
        summary = item.get("summary") or {}
        run_ids = list(summary.get("run_ids") or [])
        if (summary.get("replicas") != expected_replicas
                or len(run_ids) != expected_replicas
                or len(set(run_ids)) != len(run_ids)):
            errors.append(
                f"round {item.get('round')}: incomplete or duplicate full replica set")
        all_summary_run_ids.extend(run_ids)
    if len(all_summary_run_ids) != len(set(all_summary_run_ids)):
        errors.append("one Runtime run is reused by multiple logical configurations")
    runtime_by_id = {item["run_id"]: item for item in evidence["evaluations"]}
    for item in full:
        summary = item.get("summary") or {}
        observed_seeds = [runtime_by_id.get(run_id, {}).get("or_seed")
                          for run_id in summary.get("run_ids") or []]
        if observed_seeds != expected_seeds:
            errors.append(
                f"round {item.get('round')}: paired OR_SEED vector mismatch")
    if manifest.get("paired_or_seeds") != expected_seeds:
        errors.append("cell manifest and checkpoint OR_SEED vector mismatch")
    anytime = anytime_hypervolume_summary(
        state.get("optimization_trace"), budget=int(state.get("max_rounds") or 1),
        checkpoints=tuple(item for item in budget_checkpoints
                          if item <= int(state.get("max_rounds") or 1)))
    improvement = baseline_improvement_summary(
        history, budget=int(state.get("max_rounds") or 1),
        checkpoints=tuple(item for item in budget_checkpoints
                          if item <= int(state.get("max_rounds") or 1)))
    return {
        "cell": cell.name, "eligible": not errors, "errors": errors,
        "manifest": manifest, "terminal_status": state.get("status"),
        "protocol_fingerprint": state.get("protocol_fingerprint"),
        "logical_budget": state.get("max_rounds"), "logical_round": state.get("round"),
        "history_count": len(history), "full_configuration_count": len(full),
        "baseline_summary": (baseline_rows[0].get("summary")
                             if len(baseline_rows) == 1 else None),
        "quick_only_configuration_count": len(quick_only),
        "feasible_full_configuration_count": len(feasible),
        "best_observed": ({
            "round": best.get("round"), "candidate_id": best.get("candidate_id"),
            "utility": best.get("utility"), "parameters": best.get("parameters"),
            "summary": best.get("summary"),
        } if best else None),
        "optimization_trace": state.get("optimization_trace"),
        "anytime_hypervolume": anytime,
        "baseline_improvement": improvement,
        "promotion_history": state.get("promotion_history", []),
        "runtime_evidence": evidence,
        "runtime_cost": runtime_cost,
        "claim_boundary": "Only repeated full-flow common-evaluator observations are final QoR; quick proxy rows are excluded.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.campaign.expanduser().resolve()
    manifest = json.loads((root / "campaign-manifest.json").read_text(encoding="utf-8"))
    protocol_path = Path(manifest["protocol_path"]).expanduser().resolve()
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    if protocol.get("protocol_digest") != manifest["protocol_digest"]:
        raise ValueError("campaign protocol path and digest mismatch")
    source_snapshot = protocol.get("reproducibility", {}).get("source_snapshot", {})
    rows = [aggregate_cell(
        root / "cells" / cell["cell_id"], protocol_digest=manifest["protocol_digest"],
        budget_checkpoints=tuple(protocol["budget_checkpoints"]),
        campaign_controller_source_sha256=manifest.get(
            "controller_source_snapshot_sha256"),
        campaign_python_environment_sha256=manifest.get(
            "python_environment_fingerprint"),
        expected_reference_fingerprint=source_snapshot.get(
            f"{cell['platform']}/{cell['design']}"))
        for cell in manifest["cells"]]
    result = {
        "schema_version": 2, "kind": "industrial-dse-evidence-aggregation",
        "study_id": protocol.get("study_id"),
        "protocol_digest": manifest["protocol_digest"],
        "campaign_fingerprint": manifest["campaign_fingerprint"], "cells": rows,
        "eligible_cell_count": sum(item["eligible"] for item in rows),
        "ineligible_cell_count": sum(not item["eligible"] for item in rows),
        "all_cells_eligible": all(item["eligible"] for item in rows),
        "claim_boundary": "This verifies evidence eligibility and summarizes cells; superiority requires preregistered paired statistics across all primary cells.",
    }
    output = (args.output.expanduser().resolve() if args.output else
              root / "evidence-aggregation.json")
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    print(json.dumps({"output": str(output),
                      "all_cells_eligible": result["all_cells_eligible"]}))
    return 0 if result["all_cells_eligible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
