#!/usr/bin/env python3
"""Run one real A2 proposal -> ORFS/evaluator -> A2 feedback acceptance."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
for source_root in (ROOT, *(ROOT / "packages" / name / "src" for name in
                            ("contracts", "execution", "scheduler", "analysis"))):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from apps.l1_workbench.l2_campaign_evidence import ORFSAgentCampaignEvidence
from openroad_platform_analysis import ORFSProtectedEvaluator
from openroad_platform_execution import (
    A2_ORFO_UPSTREAM_COMMIT, A2ORFODomain, ORFSAgentFullDomain, PluginRegistry,
    a2_orfo_plugin_manifest, build_a2_orfo_policy_task,
    build_orfs_agent_full_candidate_task, orfs_agent_full_protocol_receipts,
    orfs_agent_plugin_manifest,
)
from openroad_platform_scheduler import PipelineCheckpointStore, RuntimeStore, WorkflowRuntime


ORFS_AGENT_COMMIT = "730f1fa11f9c17c0aaac332412af2b2538f42e9b"
ORFS_COMMIT = "ce8d36a7fef0ab9c47d183bcf078bce0f60f5a54"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _registered_json(runtime: WorkflowRuntime, run_id: str, kind: str) -> tuple[dict, Any]:
    matches = []
    for stage in runtime.describe(run_id)["stages"]:
        for attempt in stage["attempts"]:
            for artifact in attempt["artifacts"]:
                if artifact["kind"] == kind:
                    path = (Path(attempt["workspace"]) / artifact["store_key"]).resolve()
                    if _sha256(path) != artifact["sha256"]:
                        raise ValueError(f"registered {kind} artifact changed")
                    matches.append((artifact, json.loads(path.read_text(encoding="utf-8"))))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one registered {kind} artifact")
    return matches[0]


def _historical_rows(checkpoint: Mapping[str, Any], *, extra_smoke: Path) -> list[dict[str, Any]]:
    state = checkpoint["state"]
    rows = [dict(row) for row in state.get("observations", ())
            if row.get("status") == "succeeded" and isinstance(row.get("metrics"), Mapping)]
    summary = json.loads((extra_smoke / "summary.json").read_text(encoding="utf-8"))
    reports = list((extra_smoke / "work").rglob("protected_orfs_agent_evaluation.json"))
    if summary.get("status") != "succeeded" or len(reports) != 1:
        raise ValueError("extra historical candidate smoke is not uniquely verifiable")
    evaluation = json.loads(reports[0].read_text(encoding="utf-8"))
    task = summary["task"]
    rows.append({
        "run_id": summary["run_id"], "observation_id": f"historical-smoke-{summary['run_id']}",
        "status": "succeeded", "feasible": bool(evaluation.get("feasible")),
        "candidate": dict(task["inputs"]["candidate"]),
        "metrics": dict(evaluation["run_metadata"]["upstream_variable_clock_metrics"]),
        "artifact_refs": [f"sha256:{_sha256(reports[0])}:protected-evaluation"],
        "source_protocol_sha256": task["inputs"]["parameter_domain"]["protocol_sha256"],
        "source_kind": "independent-historical-runtime-smoke",
    })
    if len(rows) < 4:
        raise ValueError("A2 acceptance needs four prior measured successful observations")
    # Keep all valid rows: failures are valuable evidence, but the native GPR
    # currently consumes successful measurements only.
    return rows


def _normalize(rows: list[dict[str, Any]], *, protocol_sha256: str) -> list[dict[str, Any]]:
    normalized = []
    for row in rows:
        value = dict(row)
        value.setdefault("source_protocol_sha256", value.get("protocol_sha256"))
        value["protocol_sha256"] = protocol_sha256
        value["artifact_refs"] = list(value.get("artifact_refs") or ())
        normalized.append(value)
    return normalized


def _attempts(runtime: WorkflowRuntime, run_id: str) -> list[dict[str, Any]]:
    return [{
        "attempt_id": attempt["attempt_id"], "status": attempt["status"],
        "workspace": attempt["workspace"], "failure": attempt.get("failure"),
        "artifacts": [{key: item.get(key) for key in ("artifact_id", "kind", "store_key", "sha256", "metadata")}
                      for item in attempt["artifacts"]],
    } for stage in runtime.describe(run_id)["stages"] for attempt in stage["attempts"]]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--a2-source", type=Path, required=True)
    parser.add_argument("--a2-model", type=Path, required=True)
    parser.add_argument("--a2-python", type=Path, required=True)
    parser.add_argument("--codex", type=Path, required=True)
    parser.add_argument("--orfs-agent-source", type=Path, required=True)
    parser.add_argument("--paper-orfs", type=Path, required=True)
    parser.add_argument("--openroad", type=Path, required=True)
    parser.add_argument("--yosys", type=Path, required=True)
    parser.add_argument("--orfs-python", type=Path, required=True)
    parser.add_argument("--paper-environment", type=Path, required=True)
    parser.add_argument("--historical-campaign-state", type=Path, required=True)
    parser.add_argument("--historical-pipeline-id", required=True)
    parser.add_argument("--extra-candidate-smoke", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("refusing to overwrite A2 acceptance evidence")
    output.mkdir(parents=True, exist_ok=True)
    paper_environment = json.loads(args.paper_environment.read_text(encoding="utf-8"))
    receipts = orfs_agent_full_protocol_receipts(
        source_root=args.orfs_agent_source, paper_orfs_root=args.paper_orfs,
        openroad_bin=args.openroad, yosys_bin=args.yosys,
        design="aes", platform_name="sky130hd",
        paper_runtime_environment=paper_environment,
    )
    historical_store = PipelineCheckpointStore(args.historical_campaign_state)
    historical_checkpoint = historical_store.get(args.historical_pipeline_id)
    source_rows = _historical_rows(historical_checkpoint, extra_smoke=args.extra_candidate_smoke)
    a2_protocol = {
        "protocol_id": "a2-orfo-single-feedback-aes-sky130hd-v1",
        "a2_orfo_commit": A2_ORFO_UPSTREAM_COMMIT,
        "orfs_executor_commit": ORFS_AGENT_COMMIT,
        "design": "aes", "platform": "sky130hd",
        "objective_set": ["ECP", "DWL", "COMBO"],
        "seed_policy": "a2-policy-41-orfs-701",
        "budget": {"minimum_successful_observations": 4, "feedback_steps": 1},
        "evaluator": "protected-orfs-agent-full-v1",
        "objective_baselines": {"ecp": 4.721, "dwl": 589825.0},
        "design_bundle_sha256": receipts["design_bundle_sha256"],
        "pdk_bundle_sha256": receipts["pdk_bundle_sha256"],
        "toolchain_receipt_sha256": receipts["toolchain_receipt_sha256"],
    }
    a2_domain = A2ORFODomain.from_upstream(
        source_root=args.a2_source, design="aes", platform_name="sky130hd",
        experiment_protocol=a2_protocol)
    observations = _normalize(source_rows, protocol_sha256=a2_domain.protocol_sha256)
    execution_protocol = {
        "protocol_id": "a2-orfo-single-feedback-runtime-execution-v1",
        "orfs_agent_commit": ORFS_AGENT_COMMIT, "orfs_commit": ORFS_COMMIT,
        "design": "aes", "platform": "sky130hd",
        "objective_set": ["ECP", "DWL", "COMBO"],
        "seed_policy": "a2-proposal-orfs-seed-701",
        "budget": {"initial_samples": 4, "rounds": 1, "suggestions_per_round": 1,
                   "confirmations": 1},
        "evaluator": "protected-orfs-agent-full-v1",
        "initialization_method": "upstream:A2-ORFO.OptimizationWorkflow.run_iteration",
        "design_bundle_sha256": receipts["design_bundle_sha256"],
        "pdk_bundle_sha256": receipts["pdk_bundle_sha256"],
        "toolchain_receipt_sha256": receipts["toolchain_receipt_sha256"],
    }
    execution_domain = ORFSAgentFullDomain.from_upstream(
        source_root=args.orfs_agent_source, design="aes", platform="sky130hd",
        experiment_protocol=execution_protocol)
    a2_manifest = a2_orfo_plugin_manifest(
        args.a2_source, model_root=args.a2_model, python_executable=args.a2_python,
        codex_executable=args.codex, default_timeout_seconds=3600)
    executor_manifest = orfs_agent_plugin_manifest(
        args.orfs_agent_source, python_executable=args.orfs_python,
        paper_orfs_root=args.paper_orfs, openroad_bin=args.openroad,
        yosys_bin=args.yosys, paper_runtime_environment=paper_environment,
        default_timeout_seconds=10_800)
    runtime = WorkflowRuntime(
        RuntimeStore(output / "runtime.sqlite"), PluginRegistry([a2_manifest, executor_manifest]),
        workspace_root=output / "work", worker_id="a2-orfo-single-feedback",
        protected_evaluator=ORFSProtectedEvaluator(), lease_seconds=180)
    first_task = build_a2_orfo_policy_task(
        project_id="a2-orfo-acceptance", design_id="aes", objective="ECP",
        observations=observations, domain=a2_domain, n_suggestions=1,
        optimizer_seed=41, task_id="a2-orfo-first-proposal", timeout_seconds=3600)
    first = runtime.submit(first_task, capability="optimizer.l2.a2-orfo-policy")
    first_done = runtime.execute_once(first.run_id)
    if first_done.status.value != "succeeded":
        raise RuntimeError(f"first A2 policy run failed: {first_done.status.value}")
    candidate_artifact, candidates = _registered_json(runtime, first.run_id, "optimizer_candidates")
    _, checkpoint = _registered_json(runtime, first.run_id, "optimizer_checkpoint")
    if not isinstance(candidates, list) or len(candidates) != 1:
        raise ValueError("first A2 policy did not return one candidate")
    candidate = candidates[0]
    proposal_ref = f"runtime-artifact:{candidate_artifact['artifact_id']}"
    candidate_task = build_orfs_agent_full_candidate_task(
        project_id="a2-orfo-acceptance", design_id="aes", objective="ECP",
        domain=execution_domain, candidate=candidate, or_seed=701,
        proposal_origin=f"external:A2-ORFO@{A2_ORFO_UPSTREAM_COMMIT}",
        proposal_evidence_refs=(proposal_ref,), task_id="a2-orfo-runtime-candidate",
        timeout_seconds=10_800)
    candidate_run = runtime.submit(
        candidate_task, capability="optimizer.l2.upstream-full-candidate")
    candidate_done = runtime.execute_once(candidate_run.run_id)
    measured = ORFSAgentCampaignEvidence(runtime).observation_for_run(candidate_run.run_id, {})
    measured["source_protocol_sha256"] = measured["protocol_sha256"]
    measured["protocol_sha256"] = a2_domain.protocol_sha256
    observations_after_feedback = [*observations, measured]
    second_task = build_a2_orfo_policy_task(
        project_id="a2-orfo-acceptance", design_id="aes", objective="ECP",
        observations=observations_after_feedback, domain=a2_domain, n_suggestions=1,
        optimizer_seed=43, prior_checkpoint=checkpoint,
        task_id="a2-orfo-feedback-proposal", timeout_seconds=3600)
    second = runtime.submit(second_task, capability="optimizer.l2.a2-orfo-feedback")
    second_done = runtime.execute_once(second.run_id)
    if second_done.status.value != "succeeded":
        raise RuntimeError(f"A2 feedback policy run failed: {second_done.status.value}")
    _, next_candidates = _registered_json(runtime, second.run_id, "optimizer_candidates")
    summary = {
        "schema_version": 1, "kind": "a2-orfo-single-feedback-acceptance",
        "status": "succeeded", "historical_source": {
            "pipeline_id": historical_checkpoint["pipeline_id"],
            "revision": historical_checkpoint["revision"],
            "rows_used": len(observations),
            "claim": "historical ORFS measurements relabeled only into the new A2 protocol envelope; source protocol hashes retained",
        },
        "protocols": {"a2_policy": a2_protocol, "runtime_execution": execution_protocol},
        "runs": {
            "first_policy": {"run_id": first.run_id, "status": first_done.status.value,
                             "attempts": _attempts(runtime, first.run_id)},
            "candidate_execution": {"run_id": candidate_run.run_id, "status": candidate_done.status.value,
                                    "attempts": _attempts(runtime, candidate_run.run_id)},
            "feedback_policy": {"run_id": second.run_id, "status": second_done.status.value,
                                "attempts": _attempts(runtime, second.run_id)},
        },
        "feedback": measured, "first_candidate": candidate,
        "next_candidate": next_candidates[0],
        "checks": {
            "all_12_dimensions_preserved": set(candidate) == set(a2_domain.to_dict()["parameter_names"]),
            "runtime_candidate_origin_is_a2": candidate_task.labels["optimizer_origin"].startswith("external:A2-ORFO@"),
            "protected_evaluator_participated": bool(measured.get("protected_evaluation_id")),
            "failure_feedback_preserved": candidate_done.status.value != "succeeded" or not measured.get("feasible", False),
            "next_candidate_after_feedback": isinstance(next_candidates, list) and len(next_candidates) == 1,
        },
        "claim_boundary": "One real policy/execution/evaluator/feedback loop; not a campaign or PPA-superiority result.",
    }
    summary_path = output / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output / "summary.sha256").write_text(f"{_sha256(summary_path)}  summary.json\n", encoding="utf-8")
    print(json.dumps({"status": "succeeded", "summary": str(summary_path),
                      "candidate_status": candidate_done.status.value,
                      "first_policy_run_id": first.run_id,
                      "candidate_run_id": candidate_run.run_id,
                      "feedback_policy_run_id": second.run_id}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
