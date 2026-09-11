#!/usr/bin/env python3
"""Classify pinned real ORFS campaign trajectories without mutating them."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
for source_root in (ROOT, *(ROOT / "packages" / name / "src" for name in
                            ("contracts", "analysis"))):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from openroad_platform_analysis import classify_convergence  # noqa: E402
from openroad_platform_contracts import (  # noqa: E402
    ConvergencePolicy, ConvergenceState, EvidencePointer, MetricTrajectory,
    MetricTrajectoryPoint, ObjectiveDirection,
)


SOURCE_ROOT = ROOT / "var/evidence/l1-aes-to-full-l2-handoff-20260904-r3/state"
CAMPAIGN_DB = SOURCE_ROOT / "l2_campaign.sqlite"
RUNTIME_DB = SOURCE_ROOT / "runtime.sqlite"
CAMPAIGN_SHA256 = "c6eb2ad6639a0c23cb615392069aaa6a80459312365fa784120da6f452f187bb"
RUNTIME_SHA256 = "2006ae48f27a62ae1aa7801d4f4fedc5898ae2d3fed4f3051a5e160c8748b072"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _state() -> dict:
    with sqlite3.connect(f"file:{CAMPAIGN_DB}?mode=ro", uri=True) as connection:
        row = connection.execute(
            "SELECT pipeline_id,revision,state_json FROM pipeline_checkpoints_v1"
        ).fetchone()
    if row is None:
        raise ValueError("campaign checkpoint is absent")
    state = json.loads(row[2])
    return {"pipeline_id": row[0], "revision": row[1], "state": state}


def _artifact_for_run(run_id: str, *, official: bool) -> tuple[str, str, str]:
    with sqlite3.connect(f"file:{RUNTIME_DB}?mode=ro", uri=True) as connection:
        rows = connection.execute(
            "SELECT a.attempt_id,r.artifact_id,r.sha256,r.metadata_json "
            "FROM runtime_attempts a JOIN runtime_stage_runs s "
            "ON s.stage_run_id=a.stage_run_id JOIN runtime_artifacts r "
            "ON r.attempt_id=a.attempt_id WHERE s.run_id=? ORDER BY r.created_at",
            (run_id,),
        ).fetchall()
    if official:
        rows = [row for row in rows if
                json.loads(row[3]).get("runtime_authority") == "protected_evaluator"
                and json.loads(row[3]).get("official_qor") is True]
    if not rows:
        raise ValueError(f"run {run_id} lacks registered evidence")
    attempt_id, artifact_id, digest, _metadata = rows[0]
    return attempt_id, artifact_id, digest


def _successful_points(rows: list[dict], protocol: str) -> tuple[MetricTrajectoryPoint, ...]:
    points = []
    for index, row in enumerate(rows):
        run_id = row["run_id"]
        attempt_id, artifact_id, digest = _artifact_for_run(run_id, official=True)
        points.append(MetricTrajectoryPoint(
            point_id=f"point-{index}-{run_id}", sequence_index=index,
            run_id=run_id, attempt_id=attempt_id, stage="finish",
            metric="ECP_final", unit="upstream-objective",
            terminal_status="succeeded", protocol_sha256=protocol,
            authority="protected_evaluator",
            evidence=(EvidencePointer(f"artifact:runtime-{artifact_id}", digest),),
            value=float(row["metrics"]["ECP_final"]),
        ))
    return tuple(points)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("refusing to overwrite convergence acceptance evidence")
    if (_sha256(CAMPAIGN_DB), _sha256(RUNTIME_DB)) != (
            CAMPAIGN_SHA256, RUNTIME_SHA256):
        raise ValueError("completed ORFS campaign evidence drift")
    output.mkdir(parents=True, exist_ok=True)

    checkpoint = _state()
    state = checkpoint["state"]
    if state.get("status") != "completed" or state.get("round") != 5:
        raise ValueError("source campaign is not the completed five-round checkpoint")
    protocol = state["domain"]["protocol_sha256"]
    source_pointer = EvidencePointer("source:completed-orfs-campaign", CAMPAIGN_SHA256)
    policy = ConvergencePolicy(
        "l1-convergence-policy-v1", absolute_tolerance=1e-9,
        relative_tolerance=1e-6, stall_window=3, divergence_window=3,
        minimum_successful_points=2,
    )

    optimizer_rows = list(state["optimizer_observations"])
    optimizer = MetricTrajectory(
        "trajectory-optimizer-search", "ECP_final", "upstream-objective",
        ObjectiveDirection.MINIMIZE, protocol,
        _successful_points(optimizer_rows, protocol), (source_pointer,))
    optimizer_assessment = classify_convergence(optimizer, policy)

    confirmation_rows = list(state["confirmation_observations"])
    confirmation = MetricTrajectory(
        "trajectory-independent-confirmations", "ECP_final", "upstream-objective",
        ObjectiveDirection.MINIMIZE, protocol,
        _successful_points(confirmation_rows, protocol), (source_pointer,))
    confirmation_assessment = classify_convergence(confirmation, policy)

    last_failed = next(row for row in reversed(state["observations"])
                       if row["status"] != "succeeded")
    prefix = optimizer.points[-1]
    attempt_id, artifact_id, digest = _artifact_for_run(last_failed["run_id"], official=False)
    failed_point = MetricTrajectoryPoint(
        f"point-failed-{last_failed['run_id']}", prefix.sequence_index + 1,
        last_failed["run_id"], attempt_id, "finish", "ECP_final",
        "upstream-objective", last_failed["status"], protocol,
        "protected_evaluator", (EvidencePointer(
            f"artifact:runtime-{artifact_id}", digest),),
        failure_category=last_failed["failure_category"],
    )
    failure_tail = MetricTrajectory(
        "trajectory-failure-tail", "ECP_final", "upstream-objective",
        ObjectiveDirection.MINIMIZE, protocol, (prefix, failed_point),
        (source_pointer,))
    failure_assessment = classify_convergence(failure_tail, policy)

    checks = {
        "source_campaign_completed": state["status"] == "completed",
        "full_budget_retained": len(state["observations"]) == 75 and state["round"] == 5,
        "independent_confirmations_retained": len(confirmation_rows) == 3,
        "mixed_search_not_overclaimed": optimizer_assessment.state is ConvergenceState.UNKNOWN,
        "replicated_metric_is_stable": confirmation_assessment.state is ConvergenceState.STALLED,
        "failure_tail_not_hidden": failure_assessment.state is ConvergenceState.UNKNOWN and
            failure_assessment.reason_code == "latest_point_not_measured",
        "same_protocol_only": all(point.protocol_sha256 == protocol for trajectory in
                                   (optimizer, confirmation, failure_tail)
                                   for point in trajectory.points),
        "all_success_points_protected": all(point.authority == "protected_evaluator"
                                             for point in (*optimizer.points,
                                                           *confirmation.points)),
        "source_databases_unchanged": (_sha256(CAMPAIGN_DB), _sha256(RUNTIME_DB)) ==
            (CAMPAIGN_SHA256, RUNTIME_SHA256),
    }
    summary = {
        "schema_version": 1,
        "kind": "evidence-backed-convergence-acceptance",
        "accepted": all(checks.values()),
        "source": {
            "pipeline_id": checkpoint["pipeline_id"],
            "revision": checkpoint["revision"],
            "campaign_database_sha256": CAMPAIGN_SHA256,
            "runtime_database_sha256": RUNTIME_SHA256,
            "status": state["status"],
            "round": state["round"],
            "measurements": len(state["observations"]),
            "successful_optimizer_observations": len(optimizer_rows),
            "independent_confirmations": len(confirmation_rows),
        },
        "policy": policy.to_dict(),
        "trajectories": {
            "optimizer_search": optimizer.to_dict(),
            "independent_confirmations": confirmation.to_dict(),
            "failure_tail": failure_tail.to_dict(),
        },
        "assessments": {
            "optimizer_search": optimizer_assessment.to_dict(),
            "independent_confirmations": confirmation_assessment.to_dict(),
            "failure_tail": failure_assessment.to_dict(),
        },
        "checks": checks,
        "claim_boundary": (
            "This is deterministic trend classification over pinned, protected-evaluator-"
            "attested measurements. Stable independent confirmations demonstrate repeated "
            "metric equality, not optimizer convergence or PPA superiority; the mixed search "
            "trajectory remains unknown, and failed measurements remain visible."
        ),
    }
    path = output / "summary.json"
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    digest = _sha256(path)
    (output / "summary.sha256").write_text(f"{digest}  summary.json\n")
    print(json.dumps({"accepted": summary["accepted"], "summary": str(path),
                      "sha256": digest}, indent=2))
    return 0 if summary["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
