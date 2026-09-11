#!/usr/bin/env python3
"""Run the managed AES/Sky130HD L1 baseline through Runtime to ``finish``."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from apps.l1_workbench.service import WorkbenchService


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--paper-orfs", type=Path, required=True)
    parser.add_argument("--openroad", type=Path, required=True)
    parser.add_argument("--yosys", type=Path, required=True)
    parser.add_argument("--ld-library-path", required=True)
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("refusing to overwrite an existing L1 evidence directory")
    output.mkdir(parents=True, exist_ok=True)
    environment = {"LD_LIBRARY_PATH": args.ld_library_path}
    service = WorkbenchService(
        output / "state", backend="orfs",
        managed_reference="orfs-agent-paper-aes-sky130hd",
        orfs_agent_paper_orfs=args.paper_orfs,
        orfs_agent_openroad_bin=args.openroad,
        orfs_agent_yosys_bin=args.yosys,
        orfs_agent_paper_environment=environment,
        model_provider="tutorial",
    )
    session = service.start(
        "Optimize AES setup timing, keep area within 3%, protect RTL and SDC, "
        "and use at most 3 EDA runs."
    )
    if session.goal_id is None:
        session = service.answer(session.session_id, [
            {"question_id": "change_scope", "field": "change_scope",
             "value": "registered_parameters_only"},
            {"question_id": "design_context", "field": "design_context",
             "value": "managed_aes_sky130hd_4p5ns_paper_baseline"},
        ])
    if session.goal_id is None:
        raise RuntimeError("managed L1 Goal did not finalize")
    plan, state = service.execute(
        session.session_id,
        "Run the operator-owned fixed 4.5 ns AES/Sky130HD baseline through "
        "Runtime to finish and retain canonical protected QoR.",
        wait=True,
    )
    runtime = service.runtime.describe(plan["run_id"])
    summary = {
        "schema_version": 1,
        "kind": "l1-managed-aes-reference-acceptance",
        "session": session.to_dict(),
        "goal": service._goal(session.trace_id, session.goal_id).to_dict(),
        "plan": plan,
        "state": state.to_dict(),
        "runtime": runtime,
        "events": service.events(session.session_id),
        "claim_boundary": (
            "One real managed L1 reference baseline through finish. It proves "
            "typed Goal/Policy/Runtime/feedback and GDS connectivity; it is not "
            "an ORFS-Agent campaign or a PPA-superiority claim."
        ),
    }
    summary_path = output / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    digest = hashlib.sha256(summary_path.read_bytes()).hexdigest()
    (output / "summary.sha256").write_text(f"{digest}  summary.json\n")
    print(json.dumps({"status": runtime["run"]["status"],
                      "run_id": plan["run_id"],
                      "summary": str(summary_path)}, indent=2))
    return 0 if runtime["run"]["status"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
