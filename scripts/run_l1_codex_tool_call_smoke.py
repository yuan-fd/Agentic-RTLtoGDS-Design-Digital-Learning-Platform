#!/usr/bin/env python3
"""Prove a real managed-Codex L1 tool proposal on frozen EDA evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

from apps.l1_workbench.service import WorkbenchService


DATABASES = (
    "trace.sqlite", "runtime.sqlite", "l2_campaign.sqlite", "sessions.sqlite",
    "loop.sqlite", "l2_handoff.sqlite", "workbench.sqlite",
)
READ_ONLY_ACCEPTANCE_TOOLS = {
    "get_design_summary", "query_timing", "query_congestion", "query_drc",
    "query_power", "query_stage_metrics", "query_artifact_excerpt",
    "compare_runs",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _backup(source: Path, target: Path) -> None:
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
        if dst.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise RuntimeError(f"SQLite backup is invalid: {source.name}")


def _artifact_for_citation(service: WorkbenchService, run_id: str,
                           citation: dict) -> dict:
    prefix = "artifact:runtime-"
    ref = citation.get("ref")
    if not isinstance(ref, str) or not ref.startswith(prefix):
        raise RuntimeError("model citation is not a Runtime artifact reference")
    artifact_id = ref.removeprefix(prefix)
    matches = []
    for stage in service.runtime.describe(run_id).get("stages", []):
        for attempt in stage.get("attempts", []):
            root = Path(attempt["workspace"]).resolve()
            for artifact in attempt.get("artifacts", []):
                if artifact.get("artifact_id") != artifact_id:
                    continue
                path = (root / artifact["store_key"]).resolve()
                path.relative_to(root)
                actual = _sha256(path)
                if actual != artifact["sha256"] or actual != citation.get("sha256"):
                    raise RuntimeError("cited Runtime artifact failed hash validation")
                matches.append({
                    "artifact_id": artifact_id, "kind": artifact["kind"],
                    "store_key": artifact["store_key"],
                    "size_bytes": path.stat().st_size, "sha256": actual,
                })
    if len(matches) != 1:
        raise RuntimeError("model citation is missing or ambiguous in Runtime")
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--paper-orfs", type=Path, required=True)
    parser.add_argument("--openroad", type=Path, required=True)
    parser.add_argument("--yosys", type=Path, required=True)
    parser.add_argument("--paper-environment", type=Path, required=True)
    args = parser.parse_args()

    baseline = args.baseline_evidence.expanduser().resolve()
    baseline_summary_path = baseline / "summary.json"
    baseline_summary = json.loads(baseline_summary_path.read_text(encoding="utf-8"))
    source_state = baseline / "state"
    output = args.output.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("refusing to overwrite a non-empty evidence directory")
    output.mkdir(parents=True, exist_ok=True)
    state = output / "state"
    state.mkdir()
    for name in DATABASES:
        _backup(source_state / name, state / name)

    environment_path = args.paper_environment.expanduser().resolve()
    environment = json.loads(environment_path.read_text(encoding="utf-8"))
    if (not isinstance(environment, dict)
            or not all(isinstance(key, str) and isinstance(value, str)
                       for key, value in environment.items())):
        raise ValueError("paper environment must be a JSON string map")

    service = WorkbenchService(
        state, backend="orfs", model_provider="codex",
        managed_reference="orfs-agent-paper-aes-sky130hd",
        orfs_agent_source=args.source,
        orfs_agent_paper_orfs=args.paper_orfs,
        orfs_agent_openroad_bin=args.openroad,
        orfs_agent_yosys_bin=args.yosys,
        orfs_agent_paper_environment=environment,
        l2_max_parallel=4,
    )
    session_id = str(baseline_summary["session"]["session_id"])
    run_id = str(baseline_summary["plan"]["run_id"])
    before_runs = {item.run_id for item in service.runtime.store.list_runs(limit=100_000)}
    result = service.model_advance(session_id, wait=False)
    after_runs = {item.run_id for item in service.runtime.store.list_runs(limit=100_000)}

    proposal = result["model_proposal"]
    call = proposal["call"]
    receipt = result["plan"].get("receipt")
    if (call.get("producer") != "codex-cli-l1-goal-v1"
            or call.get("tool") not in READ_ONLY_ACCEPTANCE_TOOLS
            or not isinstance(receipt, dict) or receipt.get("status") != "completed"
            or result["plan"].get("run_id") is not None
            or before_runs != after_runs):
        raise RuntimeError(
            "real Codex smoke did not complete one read-only typed tool action")
    citations = proposal.get("citations")
    if not isinstance(citations, list) or len(citations) != 1:
        raise RuntimeError("real Codex tool proposal requires one exact evidence citation")
    cited_artifact = _artifact_for_citation(service, run_id, citations[0])

    codex = shutil.which("codex")
    if not codex:
        raise FileNotFoundError("codex CLI disappeared after the managed invocation")
    version = subprocess.run(
        (codex, "--version"), text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, check=True,
    ).stdout.strip()
    events = service.events(session_id)
    summary = {
        "schema_version": 1,
        "kind": "real-codex-l1-semantic-tool-call",
        "baseline_anchor": {
            "evidence": str(baseline),
            "summary_sha256": _sha256(baseline_summary_path),
            "session_id": session_id,
            "trace_id": baseline_summary["session"]["trace_id"],
            "goal_id": baseline_summary["session"]["goal_id"],
            "runtime_run_id": run_id,
        },
        "provider": {
            "provider_id": "codex-cli-l1-goal-v1", "model": "gpt-5.6-terra",
            "cli_version": version, "invocation": "ephemeral read-only sandbox",
            "fallback": None,
        },
        "model_proposal": proposal,
        "policy_and_tool_result": result["plan"],
        "citation_integrity": cited_artifact,
        "runtime_invariant": {
            "runs_before": len(before_runs), "runs_after": len(after_runs),
            "new_eda_runs": 0,
        },
        "trace_tail": events[-4:],
        "claim_boundary": (
            "A real managed Codex invocation selected one typed read-only L1 tool, "
            "cited a hash-validated Runtime artifact, passed platform Policy, and "
            "received a tool receipt. It did not execute EDA, prove QoR improvement, "
            "or grant the model a shell/path/credential capability."
        ),
    }
    summary_path = output / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    digest = _sha256(summary_path)
    (output / "summary.sha256").write_text(
        f"{digest}  summary.json\n", encoding="utf-8")
    print(json.dumps({
        "status": "succeeded", "tool": call["tool"],
        "receipt_status": receipt["status"], "new_eda_runs": 0,
        "summary": str(summary_path), "summary_sha256": digest,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
