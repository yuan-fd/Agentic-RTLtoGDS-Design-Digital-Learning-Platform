#!/usr/bin/env python3
"""Start a clean full ORFS-Agent campaign from a diagnosed L1 handoff.

This recovery tool never mutates the source evidence.  It uses SQLite's online
backup API for the L1/Runtime ledgers, creates a new campaign database and
controller identity, then re-validates the frozen domain through the admitted
ORFS-Agent composition before scheduling any tool process.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

from openroad_platform_analysis import ORFSProtectedEvaluator
from openroad_platform_execution import (
    ORFSAgentFullDomain,
    PluginRegistry,
    orfs_agent_plugin_manifest,
)
from openroad_platform_scheduler import (
    ORFSAgentFullCampaignService,
    PipelineCheckpointStore,
    RuntimeStore,
    WorkflowRuntime,
)

from apps.l1_workbench.l2_campaign_evidence import ORFSAgentCampaignEvidence


CONTROL_DATABASES = (
    "sessions.sqlite",
    "workbench.sqlite",
    "loop.sqlite",
    "trace.sqlite",
    "l2_handoff.sqlite",
    "runtime.sqlite",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _backup(source: Path, target: Path) -> None:
    if not source.is_file() or target.exists():
        raise ValueError(f"backup source/target is not admissible: {source} -> {target}")
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
        check = dst.execute("PRAGMA integrity_check").fetchone()
        if check is None or check[0] != "ok":
            raise RuntimeError(f"SQLite backup integrity check failed for {source.name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-evidence", type=Path, required=True)
    parser.add_argument("--source-pipeline-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--orfs-agent-source", type=Path, required=True)
    parser.add_argument("--orfs-agent-paper-orfs", type=Path, required=True)
    parser.add_argument("--orfs-agent-openroad-bin", type=Path, required=True)
    parser.add_argument("--orfs-agent-yosys-bin", type=Path, required=True)
    parser.add_argument("--orfs-agent-paper-environment", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    args = parser.parse_args()

    source_evidence = args.source_evidence.expanduser().resolve()
    source_state = source_evidence / "state"
    output = args.output.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("refusing to overwrite a non-empty campaign evidence directory")
    output.mkdir(parents=True, exist_ok=True)
    target_state = output / "state"
    target_state.mkdir()

    old_store = PipelineCheckpointStore(source_state / "l2_campaign.sqlite")
    old = old_store.get(args.source_pipeline_id)
    old_state = old["state"]
    if old_state.get("status") != "diagnosis_required":
        raise ValueError("campaign restart requires a diagnosis_required source checkpoint")
    for name in CONTROL_DATABASES:
        _backup(source_state / name, target_state / name)

    environment_path = args.orfs_agent_paper_environment.expanduser().resolve()
    environment = json.loads(environment_path.read_text(encoding="utf-8"))
    if (not isinstance(environment, dict)
            or not all(isinstance(k, str) and isinstance(v, str)
                       for k, v in environment.items())):
        raise ValueError("paper environment must be a JSON string map")
    copied_environment = output / "paper-environment.json"
    shutil.copy2(environment_path, copied_environment)

    manifest = orfs_agent_plugin_manifest(
        args.orfs_agent_source, python_executable=args.python,
        paper_orfs_root=args.orfs_agent_paper_orfs,
        openroad_bin=args.orfs_agent_openroad_bin,
        yosys_bin=args.orfs_agent_yosys_bin,
        paper_runtime_environment=environment,
        default_timeout_seconds=10_800,
    )
    runtime = WorkflowRuntime(
        RuntimeStore(target_state / "runtime.sqlite"), PluginRegistry([manifest]),
        workspace_root=target_state / "work",
        worker_id="orfs-agent-clean-restart-configurer",
        protected_evaluator=ORFSProtectedEvaluator(), lease_seconds=180,
    )
    checkpoints = PipelineCheckpointStore(target_state / "l2_campaign.sqlite")
    evidence = ORFSAgentCampaignEvidence(runtime)
    service = ORFSAgentFullCampaignService(
        checkpoints=checkpoints, runtime=runtime, runtime_store=runtime.store,
        observation_for_run=evidence.observation_for_run,
        candidates_for_run=evidence.candidates_for_run,
    )
    required = (
        "authorization", "request", "goal", "source_state",
        "optimizer_plugin", "protocol_mode", "domain", "objective",
        "initialization_seed", "screening_seed", "confirmation_seeds",
    )
    missing = [key for key in required if key not in old_state]
    if missing:
        raise ValueError(f"source checkpoint lacks frozen fields: {missing}")
    authorization_id = str(old_state["authorization"]["authorization_id"])
    initial_state = {
        "status": "authorized",
        "authorization": old_state["authorization"],
        "request": old_state["request"],
        "goal": old_state["goal"],
        "source_state": old_state["source_state"],
        "optimizer_plugin": old_state["optimizer_plugin"],
        "protocol_mode": old_state["protocol_mode"],
        "recovery": {
            "source_pipeline_id": old["pipeline_id"],
            "source_revision": old["revision"],
            "source_terminal_status": old_state["status"],
            "source_completion_reason": old_state.get("completion_reason"),
            "rule": "new controller; no source observation or run id is imported into this campaign",
        },
        "claim_boundary": "authorized clean restart; no measurement scheduled yet",
    }
    created = checkpoints.create_or_get(
        pipeline_kind="orfs-agent-full-campaign-v1",
        subject_id=authorization_id, owner_id=old.get("owner_id"),
        initial_state=initial_state,
    )
    domain = ORFSAgentFullDomain.from_dict(old_state["domain"])
    configured = service.configure(
        created["pipeline_id"], domain=domain, objective=str(old_state["objective"]),
        initialization_seed=int(old_state["initialization_seed"]),
        screening_seed=int(old_state["screening_seed"]),
        confirmation_seeds=tuple(int(value) for value in old_state["confirmation_seeds"]),
    )
    state = configured["state"]
    if (state.get("status") != "initialization_pending"
            or state.get("required_eda_runs") != 78
            or len(state["domain"]["parameter_names"]) != 12
            or state["domain"]["variable_clock_semantics"] is not True):
        raise RuntimeError("clean restart did not reproduce the complete frozen campaign")

    summary = {
        "schema_version": 1,
        "kind": "orfs-agent-full-campaign-clean-restart",
        "source": {
            "evidence": str(source_evidence),
            "pipeline_id": old["pipeline_id"],
            "revision": old["revision"],
            "status": old_state["status"],
            "completion_reason": old_state.get("completion_reason"),
        },
        "new_controller": configured,
        "runtime_snapshot": {
            "source_database": str(source_state / "runtime.sqlite"),
            "target_database": str(target_state / "runtime.sqlite"),
            "target_sha256": _sha256(target_state / "runtime.sqlite"),
            "historical_runs_are_ledger_only": True,
        },
        "paper_environment": {
            "path": str(copied_environment),
            "sha256": _sha256(copied_environment),
        },
        "claim_boundary": (
            "Fresh controller from the same accepted L1 authorization. Historical r2 "
            "Runtime records remain as audit evidence but are not observations, budget, "
            "or candidates of the new campaign. No EDA measurement has run yet."
        ),
    }
    summary_path = output / "restart-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    digest = _sha256(summary_path)
    (output / "restart-summary.sha256").write_text(
        f"{digest}  restart-summary.json\n")
    print(json.dumps({
        "status": state["status"], "pipeline_id": configured["pipeline_id"],
        "summary": str(summary_path), "summary_sha256": digest,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
