#!/usr/bin/env python3
"""Exercise the real Codex GoalDraft boundary without creating a Runtime run."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from apps.l1_workbench.service import WorkbenchService


def _sha256_json(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--paper-orfs", type=Path, required=True)
    parser.add_argument("--openroad", type=Path, required=True)
    parser.add_argument("--yosys", type=Path, required=True)
    parser.add_argument("--ld-library-path", default="")
    args = parser.parse_args()

    output = args.output.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("refusing to overwrite an existing L1 evidence directory")
    output.mkdir(parents=True, exist_ok=True)
    request_text = (
        "Help me optimize the managed AES/Sky130HD reference. Ask for every "
        "operator-required clarification before any EDA work."
    )
    service = WorkbenchService(
        output / "state", backend="orfs",
        managed_reference="orfs-agent-paper-aes-sky130hd",
        orfs_agent_paper_orfs=args.paper_orfs,
        orfs_agent_openroad_bin=args.openroad,
        orfs_agent_yosys_bin=args.yosys,
        orfs_agent_paper_environment=(
            {"LD_LIBRARY_PATH": args.ld_library_path}
            if args.ld_library_path else {}
        ),
        model_provider="codex",
    )
    session = service.start(request_text)
    draft, _policy = service.sessions.store.draft_and_policy(session.session_id)
    expected_questions = [item.to_dict() for item in service.required_goal_questions]
    actual_questions = [item.to_dict() for item in draft.questions]
    runtime_runs = service.runtime.store.list_runs()
    if actual_questions != expected_questions:
        raise RuntimeError("Codex output changed the operator-owned GoalDraft schema")
    if runtime_runs:
        raise RuntimeError("GoalDraft smoke unexpectedly created a Runtime run")
    provider = service._goal_provider()
    version = subprocess.run(
        [provider.executable, "--version"], text=True, check=False,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    ).stdout.strip()
    summary = {
        "schema_version": 1,
        "kind": "l1-real-codex-operator-goal-schema-smoke",
        "request_text": request_text,
        "request_sha256": hashlib.sha256(request_text.encode()).hexdigest(),
        "provider": {
            "provider_id": provider.provider_id,
            "model": provider.model,
            "cli_version": version,
            "execution": "ephemeral/read-only/no-fallback",
        },
        "session": session.to_dict(),
        "draft": draft.to_dict(),
        "operator_questions": expected_questions,
        "operator_questions_sha256": _sha256_json(expected_questions),
        "provider_questions_sha256": _sha256_json(actual_questions),
        "schema_exact_match": actual_questions == expected_questions,
        "runtime_run_count": len(runtime_runs),
        "claim_boundary": (
            "A real managed-login Codex invocation preserved the complete "
            "operator-owned GoalDraft schema. No EDA task or Runtime run was "
            "created; this is not evidence of physical-design or QoR behavior."
        ),
    }
    summary_path = output / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    digest = hashlib.sha256(summary_path.read_bytes()).hexdigest()
    (output / "summary.sha256").write_text(f"{digest}  summary.json\n")
    print(json.dumps({
        "status": session.status.value,
        "schema_exact_match": True,
        "runtime_run_count": 0,
        "summary": str(summary_path),
        "summary_sha256": digest,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
