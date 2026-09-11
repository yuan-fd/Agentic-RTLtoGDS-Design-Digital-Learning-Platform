#!/usr/bin/env python3
"""Run one complete 12-D ORFS-Agent candidate as an integration smoke."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from openroad_platform_analysis import ORFSProtectedEvaluator
from openroad_platform_execution import (
    ORFSAgentFullDomain, PluginRegistry, build_orfs_agent_full_candidate_task,
    orfs_agent_full_protocol_receipts, orfs_agent_plugin_manifest,
)
from openroad_platform_scheduler import RuntimeStore, WorkflowRuntime


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--paper-orfs", type=Path, required=True)
    parser.add_argument("--openroad", type=Path, required=True)
    parser.add_argument("--yosys", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--ld-library-path", required=True)
    parser.add_argument("--candidate-json", type=Path, required=True,
                        help="a preserved complete candidate emitted by upstream ORFS-Agent")
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("refusing to overwrite an existing smoke evidence directory")
    output.mkdir(parents=True, exist_ok=True)
    runtime_environment = {"LD_LIBRARY_PATH": args.ld_library_path}
    receipts = orfs_agent_full_protocol_receipts(
        source_root=args.source, paper_orfs_root=args.paper_orfs,
        openroad_bin=args.openroad, yosys_bin=args.yosys,
        design="aes", platform_name="sky130hd",
        paper_runtime_environment=runtime_environment,
    )
    protocol = {
        "protocol_id": "orfs-agent-full-candidate-smoke-v1",
        "orfs_agent_commit": "730f1fa11f9c17c0aaac332412af2b2538f42e9b",
        "orfs_commit": "ce8d36a7fef0ab9c47d183bcf078bce0f60f5a54",
        "design": "aes", "platform": "sky130hd",
        "objective_set": ["ECP", "DWL", "COMBO"],
        "seed_policy": "single-candidate-integration-smoke-seed-101",
        "budget": {"initial_samples": 2, "rounds": 1,
                   "suggestions_per_round": 1, "confirmations": 1},
        "evaluator": "protected-orfs-agent-full-v1",
        "initialization_method": "upstream:OptimizationWorkflow.generate_initial_parameters",
        "design_bundle_sha256": receipts["design_bundle_sha256"],
        "pdk_bundle_sha256": receipts["pdk_bundle_sha256"],
        "toolchain_receipt_sha256": receipts["toolchain_receipt_sha256"],
    }
    domain = ORFSAgentFullDomain.from_upstream(
        source_root=args.source, design="aes", platform="sky130hd",
        experiment_protocol=protocol,
    )
    candidate_path = args.candidate_json.expanduser().resolve()
    candidate_payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    if (isinstance(candidate_payload, dict)
            and isinstance(candidate_payload.get("full_candidate"), dict)):
        candidate_payload = candidate_payload["full_candidate"]
    if not isinstance(candidate_payload, dict):
        raise ValueError("candidate JSON must contain one complete candidate object")
    candidate = {name: candidate_payload[name]
                 for name in domain.to_dict()["parameter_names"]}
    domain.validate_candidate(candidate)
    task = build_orfs_agent_full_candidate_task(
        project_id="orfs-agent-full-smoke", design_id="aes", objective="ECP",
        domain=domain, candidate=candidate, or_seed=101,
        task_id="orfs-agent-full-candidate-smoke", timeout_seconds=10_800,
    )
    manifest = orfs_agent_plugin_manifest(
        args.source, python_executable=args.python,
        paper_orfs_root=args.paper_orfs, openroad_bin=args.openroad,
        yosys_bin=args.yosys, paper_runtime_environment=runtime_environment,
        default_timeout_seconds=10_800,
    )
    runtime = WorkflowRuntime(
        RuntimeStore(output / "runtime.sqlite"), PluginRegistry([manifest]),
        workspace_root=output / "work", worker_id="orfs-agent-full-smoke",
        protected_evaluator=ORFSProtectedEvaluator(), lease_seconds=180,
    )
    run = runtime.submit(task, capability="optimizer.l2.upstream-full-candidate")
    finished = runtime.execute_once(run.run_id)
    view = runtime.describe(run.run_id)
    attempts = [attempt for stage in view["stages"] for attempt in stage["attempts"]]
    summary = {
        "schema_version": 1, "kind": "orfs-agent-full-candidate-smoke",
        "status": finished.status.value, "run_id": run.run_id,
        "task": task.to_dict(), "protocol": protocol,
        "candidate_input": {
            "path": str(candidate_path),
            "sha256": hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
            "origin": "preserved-upstream-orfs-agent-candidate",
        },
        "receipts": receipts,
        "attempts": [{"attempt_id": item["attempt_id"], "status": item["status"],
                      "workspace": item["workspace"],
                      "artifacts": [{key: artifact.get(key) for key in
                                     ("artifact_id", "kind", "store_key", "sha256", "metadata")}
                                    for artifact in item["artifacts"]],
                      "failure": item.get("failure")} for item in attempts],
        "claim_boundary": (
            "One complete 12-D candidate integration smoke; it proves Runtime, "
            "paper toolchain, raw artifacts and protected evaluation connect. "
            "It is not a completed campaign or a PPA-superiority claim."
        ),
    }
    summary_path = output / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    (output / "summary.sha256").write_text(
        hashlib.sha256(summary_path.read_bytes()).hexdigest() + "  summary.json\n")
    print(json.dumps({"status": finished.status.value, "run_id": run.run_id,
                      "summary": str(summary_path)}, indent=2))
    return 0 if finished.status.value == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
