#!/usr/bin/env python3
"""Trusted worker for durable full ORFS-Agent L2 campaign checkpoints.

The HTTP workbench may authorize, configure, and inspect a campaign, but it
never executes EDA from a request handler.  This process owns the blocking
``execute=True`` transition and reconstructs the same admitted Runtime from
operator-owned, pinned toolchain arguments.
"""
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
    PluginRegistry, ProcessAdapter, ProcessGuardian, orfs_agent_plugin_manifest,
)
from openroad_platform_scheduler import (
    ORFSAgentFullCampaignService, PipelineCheckpointStore, RuntimeStore,
    WorkflowRuntime,
)

try:
    from .l2_campaign_evidence import ORFSAgentCampaignEvidence
except ImportError:  # Direct ``python apps/l1_workbench/l2_campaign_worker.py``.
    from l2_campaign_evidence import ORFSAgentCampaignEvidence


PIPELINE_KIND = "orfs-agent-full-campaign-v1"
NON_EXECUTABLE_STATUSES = frozenset({
    "authorized", "completed", "failed", "diagnosis_required",
})


@dataclass(frozen=True)
class CampaignComposition:
    l2_checkpoints: PipelineCheckpointStore
    l2_campaign: ORFSAgentFullCampaignService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Execute durable, configured, full ORFS-Agent L2 campaigns")
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--orfs-agent-source", type=Path, required=True)
    parser.add_argument("--orfs-agent-paper-orfs", type=Path, required=True)
    parser.add_argument("--orfs-agent-openroad-bin", type=Path, required=True)
    parser.add_argument("--orfs-agent-yosys-bin", type=Path, required=True)
    parser.add_argument("--orfs-agent-paper-environment", type=Path, required=True,
                        help="reviewed JSON map for the pinned paper toolchain")
    parser.add_argument("--python", type=Path, default=Path(sys.executable),
                        help="pinned ORFS-Agent environment interpreter")
    parser.add_argument("--pipeline-id",
                        help="advance only this pipeline; otherwise scan all full campaigns")
    parser.add_argument("--max-parallel", type=int, default=1)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--once", action="store_true",
                        help="perform at most one durable transition per eligible pipeline")
    return parser


def _build_service(args: argparse.Namespace) -> CampaignComposition:
    environment = json.loads(
        args.orfs_agent_paper_environment.expanduser().resolve().read_text(
            encoding="utf-8"))
    if (not isinstance(environment, dict)
            or not all(isinstance(key, str) and isinstance(value, str)
                       for key, value in environment.items())):
        raise ValueError("paper environment must be a JSON string-to-string object")
    root = args.state_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    manifest = orfs_agent_plugin_manifest(
        args.orfs_agent_source, python_executable=args.python,
        paper_orfs_root=args.orfs_agent_paper_orfs,
        openroad_bin=args.orfs_agent_openroad_bin,
        yosys_bin=args.orfs_agent_yosys_bin,
        paper_runtime_environment=environment,
        default_timeout_seconds=10_800,
    )
    runtime = WorkflowRuntime(
        RuntimeStore(root / "runtime.sqlite"), PluginRegistry([manifest]),
        workspace_root=root / "work",
        worker_id=f"orfs-agent-full-worker-{os.getpid()}",
        adapter=ProcessAdapter(ProcessGuardian()),
        protected_evaluator=ORFSProtectedEvaluator(), lease_seconds=180,
    )
    checkpoints = PipelineCheckpointStore(root / "l2_campaign.sqlite")
    evidence = ORFSAgentCampaignEvidence(runtime)
    return CampaignComposition(
        checkpoints,
        ORFSAgentFullCampaignService(
            checkpoints=checkpoints, runtime=runtime, runtime_store=runtime.store,
            observation_for_run=evidence.observation_for_run,
            candidates_for_run=evidence.candidates_for_run,
        ),
    )


def advance_eligible_once(service: Any, *, pipeline_id: str | None,
                          max_parallel: int) -> list[dict[str, Any]]:
    """Advance each selected configured campaign by one durable transition."""
    if max_parallel < 1:
        raise ValueError("max_parallel must be at least one")
    checkpoints = ([service.l2_checkpoints.get(pipeline_id)] if pipeline_id else
                   service.l2_checkpoints.list(pipeline_kind=PIPELINE_KIND, limit=1000))
    transitions: list[dict[str, Any]] = []
    for checkpoint in checkpoints:
        before = str(checkpoint["state"].get("status"))
        if before in NON_EXECUTABLE_STATUSES:
            continue
        updated = service.l2_campaign.advance(
            checkpoint["pipeline_id"], execute=True, max_parallel=max_parallel)
        transitions.append({
            "pipeline_id": checkpoint["pipeline_id"],
            "revision": updated["revision"],
            "before": before,
            "after": str(updated["state"].get("status")),
        })
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

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    while not stopping:
        transitions = advance_eligible_once(
            service, pipeline_id=args.pipeline_id, max_parallel=args.max_parallel)
        print(json.dumps({"kind": "orfs-agent-full-campaign-worker",
                          "transitions": transitions}, sort_keys=True), flush=True)
        if args.once:
            return 0
        if args.pipeline_id:
            checkpoint = service.l2_checkpoints.get(args.pipeline_id)
            if str(checkpoint["state"].get("status")) in {
                    "completed", "failed", "diagnosis_required"}:
                return 0
        time.sleep(args.poll_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
