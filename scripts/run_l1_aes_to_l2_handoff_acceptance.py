#!/usr/bin/env python3
"""Continue the accepted AES L1 session through a durable full-L2 handoff."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from apps.l1_workbench.service import WorkbenchService


DATABASES = (
    "trace.sqlite", "runtime.sqlite", "l2_campaign.sqlite", "sessions.sqlite",
    "loop.sqlite", "l2_handoff.sqlite", "workbench.sqlite",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _backup_sqlite(source: Path, target: Path) -> None:
    with sqlite3.connect(source) as origin, sqlite3.connect(target) as copy:
        origin.backup(copy)


def _artifact_integrity(view: dict) -> dict:
    checked = []
    for stage in view.get("stages", []):
        for attempt in stage.get("attempts", []):
            workspace = Path(attempt["workspace"]).resolve()
            for artifact in attempt.get("artifacts", []):
                path = (workspace / artifact["store_key"]).resolve()
                try:
                    path.relative_to(workspace)
                except ValueError as exc:
                    raise RuntimeError("registered artifact escapes its Runtime workspace") from exc
                actual_size = path.stat().st_size
                actual_sha256 = _sha256(path)
                if (actual_size != artifact["size_bytes"]
                        or actual_sha256 != artifact["sha256"]):
                    raise RuntimeError("registered candidate artifact failed integrity audit")
                checked.append({
                    "artifact_id": artifact["artifact_id"],
                    "kind": artifact["kind"], "store_key": artifact["store_key"],
                    "size_bytes": actual_size, "sha256": actual_sha256,
                })
    return {
        "checked": len(checked),
        "unique_store_keys": len({item["store_key"] for item in checked}),
        "mismatches": 0,
        "artifacts": checked,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--paper-orfs", type=Path, required=True)
    parser.add_argument("--openroad", type=Path, required=True)
    parser.add_argument("--yosys", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--ld-library-path", required=True)
    parser.add_argument("--resume", action="store_true",
                        help="resume this runner after a post-candidate assertion failure")
    args = parser.parse_args()

    baseline_root = args.baseline_evidence.expanduser().resolve()
    baseline_summary_path = baseline_root / "summary.json"
    baseline_summary = json.loads(baseline_summary_path.read_text())
    baseline_state_root = baseline_root / "state"
    output = args.output.expanduser().resolve()
    if output.exists() and any(output.iterdir()) and not args.resume:
        raise ValueError("refusing to overwrite an existing handoff evidence directory")
    state_root = output / "state"
    if args.resume:
        if not all((state_root / name).is_file() for name in DATABASES):
            raise FileNotFoundError("resumable handoff state is incomplete")
    else:
        state_root.mkdir(parents=True, exist_ok=True)
        for name in DATABASES:
            source_db = baseline_state_root / name
            if not source_db.is_file():
                raise FileNotFoundError(f"baseline state database is missing: {name}")
            _backup_sqlite(source_db, state_root / name)

    environment = {"LD_LIBRARY_PATH": args.ld_library_path}
    environment_path = output / "paper-environment.json"
    environment_payload = json.dumps(environment, sort_keys=True) + "\n"
    if args.resume and environment_path.read_text() != environment_payload:
        raise ValueError("resumed paper environment differs from the first invocation")
    if not args.resume:
        environment_path.write_text(environment_payload)
    print("continued durable AES session snapshot; constructing admitted services", flush=True)
    service = WorkbenchService(
        state_root, backend="orfs",
        managed_reference="orfs-agent-paper-aes-sky130hd",
        orfs_agent_source=args.source,
        orfs_agent_paper_orfs=args.paper_orfs,
        orfs_agent_openroad_bin=args.openroad,
        orfs_agent_yosys_bin=args.yosys,
        orfs_agent_paper_environment=environment,
        l2_max_parallel=4,
        model_provider="tutorial",
    )
    session_id = baseline_summary["session"]["session_id"]
    baseline_run_id = baseline_summary["plan"]["run_id"]
    session = service.sessions.store.get(session_id)
    if (session.trace_id != baseline_summary["session"]["trace_id"]
            or session.goal_id != baseline_summary["session"]["goal_id"]):
        raise RuntimeError("continued state changed the L1 session identity")
    current, _ = service._load(session_id)
    current_run_id = current.diagnosis.get("runtime_run_id")
    if current_run_id == baseline_run_id:
        proposal = service.propose_m1_candidate(session_id)
        print(f"running real AES candidate {proposal['proposal_id']}", flush=True)
        candidate_plan, candidate_state = service.run_candidate(
            session_id, proposal["proposal_id"],
            "Execute the single registered place-density candidate on the unchanged "
            "AES RTL/SDC/PDK/toolchain and retain protected QoR.",
            wait=True,
        )
        comparison = service.compare_m1_candidate(
            session_id, baseline_run_id,
            "Compare only canonical protected-evaluator baseline and candidate facts.",
        )
    elif args.resume and isinstance(current_run_id, str):
        candidate_state = current
        candidate_plan = {"run_id": current_run_id, "recovered": True}
        proposal = {"recovered_from_durable_trace": True}
        relevant = [event for event in service.events(session_id)
                    if event["kind"] in {"tool_called", "tool_receipt", "reflection_recorded"}]
        comparison = {"recovered_from_durable_trace": True,
                      "events": relevant[-8:]}
    else:
        raise RuntimeError("continued state is not anchored to baseline or one candidate")
    candidate_view = service.runtime.describe(candidate_plan["run_id"])
    if candidate_view["run"]["status"] != "succeeded":
        raise RuntimeError("real AES L1 candidate did not succeed")
    candidate_artifact_integrity = _artifact_integrity(candidate_view)
    print("protected L1 comparison recorded; authorizing full L2", flush=True)
    escalation = service.l2_escalate(
        session_id,
        summary="Escalate after two distinct measured AES observations; retain all full upstream dimensions.",
    )
    configured = service.l2_configure(
        session_id, escalation["pipeline_id"], objective="ECP",
        initialization_seed=401, screening_seed=401,
        confirmation_seeds=[503, 601, 699],
    )
    domain = configured["state"]["domain"]
    parameter_names = list(domain["parameter_names"])
    budget = domain["experiment_protocol"]["budget"]
    required_measurements = (
        int(budget["initial_samples"])
        + int(budget["rounds"]) * int(budget["suggestions_per_round"])
        + int(budget["confirmations"])
    )
    if (len(parameter_names) != 12 or "CLK" not in parameter_names
            or domain["variable_clock_semantics"] is not True
            or domain["experiment_protocol"]["objective_set"] != ["ECP", "DWL", "COMBO"]
            or required_measurements != 78):
        raise RuntimeError("configured L2 does not preserve the complete upstream protocol")

    worker_command = [
        sys.executable, "apps/l1_workbench/l2_campaign_worker.py",
        "--state-root", str(state_root),
        "--orfs-agent-source", str(args.source.expanduser().resolve()),
        "--orfs-agent-paper-orfs", str(args.paper_orfs.expanduser().resolve()),
        "--orfs-agent-openroad-bin", str(args.openroad.expanduser().resolve()),
        "--orfs-agent-yosys-bin", str(args.yosys.expanduser().resolve()),
        "--orfs-agent-paper-environment", str(environment_path),
        "--python", str(args.python.expanduser().resolve()),
        "--pipeline-id", escalation["pipeline_id"],
        "--max-parallel", "4", "--once",
    ]
    if configured["state"]["status"] == "initialization_pending":
        print("starting independent worker for one durable transition", flush=True)
        worker = subprocess.run(
            worker_command, cwd=Path(__file__).resolve().parents[1],
            env=dict(os.environ), text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=False,
        )
        if worker.returncode != 0:
            raise RuntimeError("independent L2 worker failed: " + worker.stderr[-2000:])
        worker_returncode, worker_stdout, worker_stderr = (
            worker.returncode, worker.stdout, worker.stderr)
    elif args.resume and configured["state"]["status"] == "initialization_running":
        worker_returncode = 0
        worker_stdout = "recovered completed independent-worker transition from durable state"
        worker_stderr = ""
    else:
        raise RuntimeError("configured controller is not at the worker handoff boundary")
    after_worker = service.l2_status(session_id, escalation["pipeline_id"])
    if after_worker["state"]["status"] != "initialization_running":
        raise RuntimeError("independent worker did not claim the configured controller")
    initializer_run_id = after_worker["state"]["initialization_run_id"]
    initializer_view = service.runtime.describe(initializer_run_id)
    if (initializer_view["run"]["status"] != "queued"
            or initializer_view["run"]["task_spec"]["inputs"].get("mode")
            != "upstream_full_initialize"):
        raise RuntimeError("worker did not create the bounded upstream initializer task")

    summary = {
        "schema_version": 1,
        "kind": "same-session-aes-l1-to-full-l2-handoff",
        "baseline_anchor": {
            "evidence": str(baseline_root),
            "summary_sha256": _sha256(baseline_summary_path),
            "session_id": session_id,
            "trace_id": session.trace_id,
            "goal_id": session.goal_id,
            "run_id": baseline_run_id,
            "state_database_backup": "SQLite online backup into this evidence root",
        },
        "protected_inputs": {
            "design_bundle_sha256": service.reference_design.source_fingerprint,
            "sdc_sha256": _sha256(service.reference_design.sdc_path),
            "orfs_commit": service.reference_design.orfs_commit,
            "changed": False,
        },
        "l1": {
            "proposal": proposal,
            "candidate_plan": candidate_plan,
            "candidate_state": candidate_state.to_dict(),
            "candidate_runtime": candidate_view,
            "candidate_artifact_integrity": candidate_artifact_integrity,
            "comparison": comparison,
        },
        "l2": {
            "escalation": escalation,
            "configured_checkpoint": configured,
            "after_independent_worker": after_worker,
            "initializer_runtime": initializer_view,
            "domain_assertions": {
                "parameter_count": len(parameter_names),
                "parameter_names": parameter_names,
                "variable_clock": domain["variable_clock_semantics"],
                "objective_set": domain["experiment_protocol"]["objective_set"],
                "budget": budget,
                "required_measurements": required_measurements,
            },
            "worker": {
                "separate_process": True,
                "returncode": worker_returncode,
                "stdout": worker_stdout,
                "stderr": worker_stderr,
                "command_without_environment_values": worker_command,
            },
        },
        "environment_receipt": {
            "path": str(environment_path),
            "sha256": _sha256(environment_path),
        },
        "claim_boundary": (
            "One real AES L1 baseline/candidate/compare/reflection to a fully "
            "configured 78-measurement ORFS-Agent controller and independent "
            "worker handoff. The queued initializer is not yet a completed "
            "campaign or a PPA-superiority result."
        ),
    }
    summary_path = output / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    digest = _sha256(summary_path)
    (output / "summary.sha256").write_text(f"{digest}  summary.json\n")
    print(json.dumps({
        "status": after_worker["state"]["status"],
        "session_id": session_id,
        "baseline_run_id": baseline_run_id,
        "candidate_run_id": candidate_plan["run_id"],
        "pipeline_id": escalation["pipeline_id"],
        "initializer_run_id": initializer_run_id,
        "required_measurements": required_measurements,
        "summary_sha256": digest,
    }, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
