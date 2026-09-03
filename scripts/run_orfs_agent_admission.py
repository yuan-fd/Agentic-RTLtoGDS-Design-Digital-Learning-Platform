#!/usr/bin/env python3
"""Bounded, reproducible admission smoke for the pinned ORFS-Agent plugin.

This is evidence infrastructure, not a replacement optimizer.  It exercises
the product L2 orchestration service with three measured ORFS baselines, the
pinned upstream ORFS-Agent GP/EI proposal path, then repeated Runtime ORFS
evaluation of one proposed vector.  It intentionally makes no PPA-improvement
claim: one bounded campaign only proves integration and evidence continuity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
for source_root in (
    ROOT,
    ROOT / "packages/contracts/src",
    ROOT / "packages/execution/src",
    ROOT / "packages/scheduler/src",
    ROOT / "packages/analysis/src",
    ROOT / "packages/visualization/src",
):
    sys.path.insert(0, str(source_root))

from openroad_platform_scheduler.external_l2_service import (  # noqa: E402
    EXTERNAL_L2_KIND, ExternalOptimizerLoopService,
)
from openroad_platform_analysis.learning_data import RuntimeEvidenceExporter  # noqa: E402
from openroad_platform_analysis.orfs_protected_evaluator import ORFSProtectedEvaluator  # noqa: E402
from openroad_platform_contracts.learning import LearningContext  # noqa: E402
from openroad_platform_contracts.platform import RuntimeStatus, TaskSpec  # noqa: E402
from openroad_platform_execution.orfs_agent_plugin import (  # noqa: E402
    build_orfs_agent_native_task, orfs_agent_plugin_manifest,
)
from openroad_platform_execution.orfs_parameters import orfs_optimization_profile  # noqa: E402
from openroad_platform_execution.orfs_plugin import build_orfs_task, orfs_plugin_manifest  # noqa: E402
from openroad_platform_execution.registry import PluginRegistry  # noqa: E402
from openroad_platform_execution.toolchain import ToolchainConfig  # noqa: E402
from openroad_platform_scheduler.pipeline_checkpoint import PipelineCheckpointStore  # noqa: E402
from openroad_platform_scheduler.runtime import WorkflowRuntime  # noqa: E402
from openroad_platform_scheduler.runtime_store import RuntimeStore  # noqa: E402


COMMON_EVALUATION = "orfs/implementation/analysis/common_evaluation.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_receipt(source: Path) -> dict[str, Any]:
    return {
        "source_root": str(source),
        "commit": command(("git", "-C", str(source), "rev-parse", "HEAD")),
        "status": command(("git", "-C", str(source), "status", "--porcelain=v1", "--untracked-files=all")),
        "license_sha256": sha256(source / "LICENSE"),
    }


def command(argv: Sequence[str]) -> str:
    completed = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, timeout=60, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(argv)}\n{completed.stdout}")
    return completed.stdout.rstrip()


def common_evaluation(runtime_store: RuntimeStore, run_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    description = runtime_store.describe_run(run_id)
    attempts = [attempt for stage in description["stages"] for attempt in stage["attempts"]]
    if len(attempts) != 1:
        raise ValueError(f"expected one attempt for admission run {run_id}")
    attempt = attempts[0]
    artifact = next((item for item in attempt["artifacts"]
                     if item["store_key"] == COMMON_EVALUATION), None)
    if artifact is None:
        raise ValueError(f"canonical QoR artifact is absent for {run_id}")
    path = (Path(attempt["workspace"]) / artifact["store_key"]).resolve()
    if not path.is_file() or path.stat().st_size != artifact["size_bytes"]:
        raise ValueError(f"canonical QoR artifact size mismatch for {run_id}")
    if sha256(path) != artifact["sha256"]:
        raise ValueError(f"canonical QoR artifact hash mismatch for {run_id}")
    return json.loads(path.read_text(encoding="utf-8")), artifact


def candidate_artifact(runtime_store: RuntimeStore, run_id: str) -> list[dict[str, Any]]:
    description = runtime_store.describe_run(run_id)
    attempts = [attempt for stage in description["stages"] for attempt in stage["attempts"]]
    if len(attempts) != 1 or attempts[0]["status"] != "succeeded":
        raise ValueError("ORFS-Agent Runtime attempt did not succeed")
    attempt = attempts[0]
    artifact = next((item for item in attempt["artifacts"]
                     if item["kind"] == "optimizer_candidates"), None)
    if artifact is None:
        raise ValueError("ORFS-Agent emitted no candidate artifact")
    path = (Path(attempt["workspace"]) / artifact["store_key"]).resolve()
    if (not path.is_file() or path.stat().st_size != artifact["size_bytes"]
            or sha256(path) != artifact["sha256"]):
        raise ValueError("ORFS-Agent candidate artifact failed Runtime integrity verification")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError("ORFS-Agent candidate artifact is not a JSON object list")
    return payload


def run_summary(runtime_store: RuntimeStore, run_id: str) -> dict[str, Any]:
    run = runtime_store.get_run(run_id)
    summary: dict[str, Any] = {"run_id": run_id, "status": run.status.value}
    if run.task_spec.plugin_id == "orfs":
        if run.status is RuntimeStatus.SUCCEEDED:
            evaluation, artifact = common_evaluation(runtime_store, run_id)
            summary["canonical_evaluation"] = {
                "evaluation_id": evaluation["evaluation_id"],
                "feasible": evaluation["feasible"],
                "gate": evaluation["gate"],
                "artifact_sha256": artifact["sha256"],
            }
        else:
            attempts = [attempt for stage in runtime_store.describe_run(run_id)["stages"]
                        for attempt in stage["attempts"]]
            summary["terminal_failure"] = attempts[-1].get("failure") if attempts else None
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--orfs-agent-source", type=Path, required=True)
    parser.add_argument("--rtl", type=Path, default=ROOT / "tests/fixtures/p2_mux_2to1.v")
    parser.add_argument("--design-id", default="mux_2to1")
    parser.add_argument("--top", default="mux_2to1")
    parser.add_argument("--orfs-root", type=Path, default=Path.home() / "OpenROAD-flow-scripts")
    parser.add_argument("--openroad-bin", type=Path, default=Path.home() / "bin/openroad")
    parser.add_argument("--yosys-bin", type=Path, default=Path.home() / "bin/yosys")
    parser.add_argument("--klayout-bin", type=Path, default=Path.home() / "bin/klayout")
    parser.add_argument("--timeout", type=int, default=7200)
    parser.add_argument("--stage-timeout", type=int, default=3600)
    parser.add_argument(
        "--minimum-die-size-um", type=float, default=20.0,
        help=("Frozen physical floor for this bounded smoke.  Small synthetic RTL "
              "otherwise has no PDN geometry; this is not an optimizer knob."),
    )
    parser.add_argument("--optimizer-seed", type=int, default=20260830)
    parser.add_argument("--resume-pipeline-id", default=None,
                        help="Resume a durable admission checkpoint in --output-root.")
    args = parser.parse_args()

    output = args.output_root.expanduser().resolve()
    source = args.orfs_agent_source.expanduser().resolve()
    if not args.resume_pipeline_id and output.exists() and any(output.iterdir()):
        raise FileExistsError(f"admission output is not empty: {output}")
    if args.resume_pipeline_id and not output.is_dir():
        raise FileNotFoundError(f"admission output is missing: {output}")
    output.mkdir(parents=True, exist_ok=True)
    if not args.rtl.is_file():
        raise FileNotFoundError(args.rtl)
    receipt_before = source_receipt(source)
    if receipt_before["commit"] != "730f1fa11f9c17c0aaac332412af2b2538f42e9b":
        raise ValueError("ORFS-Agent source does not match the admitted commit")
    if receipt_before["status"]:
        raise ValueError("ORFS-Agent admission source must be a clean checkout")

    toolchain = ToolchainConfig(
        name="orfs-agent-admission-orfs",
        orfs_root=args.orfs_root.expanduser().resolve(),
        openroad_bin=args.openroad_bin.expanduser().resolve(),
        yosys_bin=args.yosys_bin.expanduser().resolve(),
        klayout_bin=args.klayout_bin.expanduser().resolve(),
    )
    toolchain.validate()
    agent_python = ROOT / ".tools/venvs/orfs-agent/bin/python"
    if not agent_python.is_file():
        raise FileNotFoundError("isolated ORFS-Agent Python environment is missing")
    manifests = [
        orfs_plugin_manifest(toolchain, default_timeout_seconds=args.timeout),
        orfs_agent_plugin_manifest(source, python_executable=agent_python),
    ]
    runtime_store = RuntimeStore(output / "runtime.db")
    runtime = WorkflowRuntime(
        runtime_store, PluginRegistry(manifests), workspace_root=output / "attempts",
        worker_id="orfs-agent-admission", lease_seconds=60,
        protected_evaluator=ORFSProtectedEvaluator(),
    )
    profile = orfs_optimization_profile("nangate45")
    baseline_parameters = dict(profile["baseline"])
    # ORFS-Agent's published shared GP/EI domain starts CTS diameter at 80;
    # keep every baseline point inside that fixed adapter intersection.
    baseline_parameters["cts_cluster_diameter"] = 80.0
    replicas = (101, 211, 307)
    design_id, top = str(args.design_id).strip(), str(args.top).strip()
    if not design_id or not top:
        raise ValueError("design-id and top are required")
    base_task = build_orfs_task(
        args.rtl, project_id="orfs-agent-admission", design_id=design_id,
        top=top, platform_name="nangate45", target_stage="finish",
        clock_period_ns=10.0, core_utilization_pct=float(baseline_parameters["core_utilization_pct"]),
        place_density=.55, or_seed=replicas[0], stage_timeout_seconds=args.stage_timeout,
        timeout_seconds=args.timeout, minimum_die_size_um=args.minimum_die_size_um,
        flow_parameters=baseline_parameters,
        labels={"admission": "orfs-agent", "role": "baseline"},
    )
    context = LearningContext(
        design_id=design_id, design_fingerprint=str(base_task.inputs["rtl"]["sha256"]),
        platform="nangate45", pdk_id="nangate45", toolchain_id="orfs2d",
        flow_stage="finish", metric_parser_version="common_eval_v3",
        constraint_fingerprint=hashlib.sha256(b"nangate45:clock_period_ns=10.0").hexdigest(),
    )

    def observation_for_run(run_id: str, _state: Mapping[str, Any]) -> Mapping[str, Any]:
        observed = RuntimeEvidenceExporter(runtime_store, use_common_evaluation=True).export_run(run_id, context)
        evaluation, _artifact = common_evaluation(runtime_store, run_id)
        return {
            "observation_id": observed.observation_id, "run_id": run_id,
            "status": observed.status, "parameters": dict(observed.parameters),
            "metrics": dict(observed.metrics),
            "artifact_refs": [item.ref for item in observed.evidence],
            "feasible": bool(evaluation["feasible"]),
            "failure_category": observed.failure_category,
        }

    def optimizer_task(observations: Sequence[Mapping[str, Any]], _state: Mapping[str, Any]) -> TaskSpec:
        shared_fixed_names = (
            "tns_end_percent", "global_placement_padding", "detail_placement_padding",
            "enable_dpo", "place_density_lb_addon", "cts_cluster_size", "cts_cluster_diameter",
        )
        fixed = {name: baseline_parameters[name] for name in shared_fixed_names}
        return build_orfs_agent_native_task(
            project_id="orfs-agent-admission", design_id=design_id, platform_name="nangate45",
            objective="optimizer_objective", observations=observations,
            n_suggestions=1, optimizer_seed=args.optimizer_seed, timeout_seconds=1800,
            search_parameter_names=["core_utilization_pct"], fixed_parameters=fixed,
            admissible_values={"core_utilization_pct": list(range(40, 71))},
        )

    service = ExternalOptimizerLoopService(
        checkpoints=PipelineCheckpointStore(output / "pipeline.db"), runtime=runtime,
        runtime_store=runtime_store, observation_for_run=observation_for_run,
        optimizer_task=optimizer_task, candidates_for_run=lambda run_id: candidate_artifact(runtime_store, run_id),
    )
    initial = {
        "status": "baseline_running", "design_id": design_id, "platform": "nangate45",
        "objective_profile": "balanced", "optimizer_plugin": "orfs-agent@2025.1",
        "base_task": base_task.to_dict(), "baseline_parameters": baseline_parameters,
        "baseline_run_ids": [], "replica_or_seeds": list(replicas), "max_candidates": 1,
        "admission_probe_recipes": [
            {"recipe_id": "utilization-45", "parameters": {"core_utilization_pct": 45}},
            {"recipe_id": "utilization-65", "parameters": {"core_utilization_pct": 65}},
        ],
        "candidates_per_round": 1, "minimum_relative_improvement": .005,
        "frozen_constraints": list(profile["frozen_constraints"]), "round": 0,
        "candidate_count": 0, "stalled_rounds": 0, "history": [], "agent_events": [],
    }
    if args.resume_pipeline_id:
        checkpoint = service.checkpoints.get(args.resume_pipeline_id)
        if checkpoint["pipeline_kind"] != EXTERNAL_L2_KIND:
            raise ValueError("resume checkpoint is not an external L2 pipeline")
        print(f"[orfs-agent-admission] resuming pipeline={checkpoint['pipeline_id']}", flush=True)
    else:
        checkpoint = service.create(subject_id=f"{design_id}-admission", owner_id=None, initial_state=initial)
        print(f"[orfs-agent-admission] pipeline={checkpoint['pipeline_id']} baselines=3", flush=True)
    baseline_done = checkpoint
    if baseline_done["state"]["status"] == "baseline_running":
        baseline_done = service.advance(checkpoint["pipeline_id"], execute=True, max_parallel=3)
    if baseline_done["state"]["status"] == "admission_probe_running":
        baseline_done = service.advance(checkpoint["pipeline_id"], execute=True, max_parallel=2)
    if baseline_done["state"]["status"] != "optimizer_pending":
        raise RuntimeError(f"baseline/probe phase did not reach optimizer_pending: {baseline_done['state']}")
    optimizer_submitted = service.advance(checkpoint["pipeline_id"], execute=False)
    if optimizer_submitted["state"]["status"] != "optimizer_running":
        raise RuntimeError("ORFS-Agent task was not submitted")
    optimizer_done = service.advance(checkpoint["pipeline_id"], execute=True, max_parallel=1)
    if optimizer_done["state"]["status"] != "candidate_running":
        raise RuntimeError(f"ORFS-Agent did not produce a candidate: {optimizer_done['state']}")
    completed = service.advance(checkpoint["pipeline_id"], execute=True, max_parallel=3)

    state = completed["state"]
    run_ids = [*state["baseline_run_ids"], state["optimizer_run_id"]]
    run_ids.extend(run_id for item in state.get("history", []) for result in item["results"]
                   for run_id in result["run_ids"])
    source_after = source_receipt(source)
    baseline_and_optimizer_ok = all(
        runtime_store.get_run(run_id).status is RuntimeStatus.SUCCEEDED
        for run_id in [*state["baseline_run_ids"], state["optimizer_run_id"]]
    )
    candidate_terminal = all(
        runtime_store.get_run(run_id).status.value in {"succeeded", "failed", "cancelled", "timed_out", "lost"}
        for run_id in run_ids[4:]
    )
    accepted = (
        completed["pipeline_kind"] == EXTERNAL_L2_KIND
        and state["status"] == "completed"
        and source_after == receipt_before
        and baseline_and_optimizer_ok and candidate_terminal
    )
    summary = {
        "schema_version": 1, "accepted": accepted,
        "claim_boundary": (
            "bounded integration admission smoke; candidate failures are retained as evidence; "
            "not a PPA-improvement study"
        ),
        "source_before": receipt_before, "source_after": source_after,
        "pipeline": completed,
        "runs": [run_summary(runtime_store, run_id) for run_id in run_ids],
        "protected_evaluator": "common-evaluator-v3",
    }
    (output / "admission_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[orfs-agent-admission] status={state['status']} accepted={accepted} runs={len(run_ids)}", flush=True)
    return 0 if accepted else 2


if __name__ == "__main__":
    raise SystemExit(main())
