#!/usr/bin/env python3
"""Trusted OS worker for durable A2-ORFO product campaigns."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from openroad_platform_analysis import ORFSProtectedEvaluator
from openroad_platform_execution import (
    PluginRegistry, ProcessAdapter, ProcessGuardian, a2_orfo_plugin_manifest,
    orfs_agent_plugin_manifest,
)
from openroad_platform_scheduler import (
    A2_ORFO_CAMPAIGN_KIND, A2ORFOCampaignService, PipelineCheckpointStore,
    RuntimeStore, WorkflowRuntime,
)

try:
    from .l2_campaign_evidence import ORFSAgentCampaignEvidence
except ImportError:
    from l2_campaign_evidence import ORFSAgentCampaignEvidence


NON_EXECUTABLE_STATUSES = frozenset({
    "authorized", "completed", "failed", "diagnosis_required",
})


@dataclass(frozen=True)
class CampaignComposition:
    l2_checkpoints: PipelineCheckpointStore
    l2_campaign: A2ORFOCampaignService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Execute configured durable A2-ORFO product campaigns")
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--a2-orfo-source", type=Path, required=True)
    parser.add_argument("--a2-orfo-model", type=Path, required=True)
    parser.add_argument("--a2-orfo-python", type=Path, required=True)
    parser.add_argument("--a2-orfo-codex", type=Path, required=True)
    parser.add_argument("--orfs-agent-source", type=Path, required=True)
    parser.add_argument("--orfs-agent-paper-orfs", type=Path, required=True)
    parser.add_argument("--orfs-agent-openroad-bin", type=Path, required=True)
    parser.add_argument("--orfs-agent-yosys-bin", type=Path, required=True)
    parser.add_argument("--orfs-agent-paper-environment", type=Path, required=True)
    parser.add_argument("--orfs-agent-python", type=Path, required=True)
    parser.add_argument("--pipeline-id")
    parser.add_argument("--max-parallel", type=int, default=1)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--once", action="store_true")
    return parser


def _build_service(args: argparse.Namespace) -> CampaignComposition:
    environment = json.loads(args.orfs_agent_paper_environment.read_text())
    if (not isinstance(environment, dict)
            or not all(isinstance(key, str) and isinstance(value, str)
                       for key, value in environment.items())):
        raise ValueError("paper environment must be a JSON string map")
    root = args.state_root.expanduser().resolve(); root.mkdir(parents=True, exist_ok=True)
    a2 = a2_orfo_plugin_manifest(
        args.a2_orfo_source, model_root=args.a2_orfo_model,
        python_executable=args.a2_orfo_python,
        codex_executable=args.a2_orfo_codex, default_timeout_seconds=3600)
    executor = orfs_agent_plugin_manifest(
        args.orfs_agent_source, python_executable=args.orfs_agent_python,
        paper_orfs_root=args.orfs_agent_paper_orfs,
        openroad_bin=args.orfs_agent_openroad_bin,
        yosys_bin=args.orfs_agent_yosys_bin,
        paper_runtime_environment=environment, default_timeout_seconds=10_800)
    runtime = WorkflowRuntime(
        RuntimeStore(root / "runtime.sqlite"), PluginRegistry([a2, executor]),
        workspace_root=root / "work", worker_id=f"a2-orfo-worker-{os.getpid()}",
        adapter=ProcessAdapter(ProcessGuardian()),
        protected_evaluator=ORFSProtectedEvaluator(), lease_seconds=180)
    checkpoints = PipelineCheckpointStore(root / "l2_campaign.sqlite")
    evidence = ORFSAgentCampaignEvidence(runtime)
    return CampaignComposition(
        checkpoints,
        A2ORFOCampaignService(
            checkpoints=checkpoints, runtime=runtime, runtime_store=runtime.store,
            observation_for_run=evidence.observation_for_run,
            policy_result_for_run=evidence.a2_policy_result_for_run))


def advance_eligible_a2_once(service: Any, *, pipeline_id: str | None,
                             max_parallel: int) -> list[dict[str, Any]]:
    if max_parallel < 1:
        raise ValueError("max_parallel must be at least one")
    checkpoints = ([service.l2_checkpoints.get(pipeline_id)] if pipeline_id else
                   service.l2_checkpoints.list(
                       pipeline_kind=A2_ORFO_CAMPAIGN_KIND, limit=1000))
    transitions = []
    for checkpoint in checkpoints:
        before = str(checkpoint["state"].get("status"))
        if before in NON_EXECUTABLE_STATUSES:
            continue
        updated = service.l2_campaign.advance(
            checkpoint["pipeline_id"], execute=True, max_parallel=max_parallel)
        transitions.append({"pipeline_id": checkpoint["pipeline_id"],
                            "revision": updated["revision"], "before": before,
                            "after": str(updated["state"].get("status"))})
    return transitions


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.poll_seconds <= 0:
        raise ValueError("poll-seconds must be positive")
    service = _build_service(args)
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop); signal.signal(signal.SIGTERM, stop)
    while not stopping:
        transitions = advance_eligible_a2_once(
            service, pipeline_id=args.pipeline_id, max_parallel=args.max_parallel)
        print(json.dumps({"kind": "a2-orfo-campaign-worker",
                          "transitions": transitions}, sort_keys=True), flush=True)
        if args.once:
            return 0
        if args.pipeline_id:
            status = service.l2_checkpoints.get(args.pipeline_id)["state"].get("status")
            if status in {"completed", "failed", "diagnosis_required"}:
                return 0
        time.sleep(args.poll_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
