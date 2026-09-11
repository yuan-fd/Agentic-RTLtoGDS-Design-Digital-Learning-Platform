#!/usr/bin/env python3
"""Replay one real failed ORFS result through durable L1 role states."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
for source_root in (ROOT, *(ROOT / "packages" / name / "src" for name in
                            ("contracts", "analysis", "scheduler", "execution"))):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from openroad_platform_analysis import diagnose_runtime  # noqa: E402
from openroad_platform_contracts import (  # noqa: E402
    AnalysisTarget, EvidencePointer, RecoveryAction,
)
from openroad_platform_scheduler import (  # noqa: E402
    L1ControlStateStore, PDAgentControlStateMachine,
)


SOURCE = ROOT / "var/evidence/a2-orfo-single-feedback-20260905-r4/summary.json"
SOURCE_SHA256 = "c11638e49bf345987afda2f7159856a67cb4b1f962ceb6a8520d95f6ff7f55aa"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("refusing to overwrite L1 control-state evidence")
    if _sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError("A2-ORFO single-feedback evidence drift")
    output.mkdir(parents=True, exist_ok=True)
    source = json.loads(SOURCE.read_text())
    candidate = source["runs"]["candidate_execution"]
    runtime_view = {
        "run": {"run_id": candidate["run_id"], "status": candidate["status"]},
        "stages": [{"stage_key": "finish", "attempts": candidate["attempts"]}],
    }
    policy_source = ROOT / "packages/analysis/src/openroad_platform_analysis/common_evaluator.py"
    policy = (EvidencePointer("source:protected-orfs-evaluator-v3",
                              _sha256(policy_source)),)
    report = diagnose_runtime(runtime_view, targets=(
        AnalysisTarget("setup_wns_ns", ">=", 0.0, "ns", policy),
        AnalysisTarget("drc_errors", "==", 0.0, "count", policy),
    ))
    official = next(
        artifact for attempt in candidate["attempts"]
        for artifact in attempt["artifacts"]
        if artifact.get("metadata", {}).get("official_qor") is True)
    official_pointer = EvidencePointer(
        f"artifact:runtime-{official['artifact_id']}", official["sha256"])
    source_pointer = EvidencePointer("source:a2-single-feedback-evidence", SOURCE_SHA256)

    store = L1ControlStateStore(output / "control.sqlite")
    machine = PDAgentControlStateMachine()
    states = []
    state = machine.initialize("goal-control-replay", ("finish",), (source_pointer,))
    store.append_planner(state); states.append(state)
    state = machine.runtime_submitted(
        state, run_id=candidate["run_id"], evidence=(official_pointer,))
    store.append_planner(state); states.append(state)
    state = machine.runtime_terminal(
        state, terminal_status=candidate["status"], evidence=(official_pointer,))
    store.append_planner(state); states.append(state)
    state, analyzer, debugger = machine.analysis_completed(state, report)
    if debugger is None:
        raise RuntimeError("real timing violation did not activate Debugger")
    store.append_analyzer(analyzer)
    store.append_planner(state); states.append(state)
    store.append_debugger(debugger)
    state, proposed = machine.propose_debug_action(
        state, debugger, action=RecoveryAction.STOP)
    store.append_debugger(proposed)
    store.append_planner(state); states.append(state)

    checks = {
        "real_input_pinned": _sha256(SOURCE) == SOURCE_SHA256,
        "protected_timing_preserved": next(
            fact.value for analysis in report.analyses for fact in analysis.facts
            if fact.metric == "setup_wns_ns") == -3.85937,
        "timing_blocker_detected": "setup_wns_ns_target_violated" in report.blockers,
        "planner_hub_path": [item.phase.value for item in states] == [
            "planning", "awaiting_runtime", "analyzing", "debugging", "failed"],
        "analyzer_bound_to_report": analyzer.diagnosis_report_id == report.report_id,
        "debugger_bound_to_facts": bool(debugger.basis_fact_ids),
        "typed_stop_not_shell": proposed.proposed_action.value == "stop",
        "recovery_budget_unchanged": state.recovery_budget.to_dict() == states[0].recovery_budget.to_dict(),
        "durable_latest_round_trip": store.latest("goal-control-replay") == state,
        "no_runtime_or_artifact_mutation": _sha256(SOURCE) == SOURCE_SHA256,
    }
    summary = {
        "schema_version": 1, "kind": "l1-pdagent-control-state-acceptance",
        "accepted": all(checks.values()),
        "reference": {
            "paper": "PDAGENT-BENCH arXiv:2606.17253v6",
            "adapted_roles": {"Planner": "L1 coordinator", "Worker": "Runtime",
                              "Analyzer": "deterministic StageAnalysis",
                              "Debugger": "typed recovery decision",
                              "Optimizer": "external L2 only"},
            "code_reuse": False,
        },
        "input_evidence": {"source_document": str(SOURCE.relative_to(ROOT)),
                           "sha256": SOURCE_SHA256},
        "planner_states": [item.to_dict() for item in states],
        "analyzer_state": analyzer.to_dict(),
        "debugger_states": [debugger.to_dict(), proposed.to_dict()],
        "diagnosis_report": report.to_dict(),
        "checks": checks,
        "claim_boundary": (
            "A durable role/state transition replay over one real protected ORFS "
            "measurement. It does not execute a fix, copy PDAGENT code, or validate "
            "PDAGENT-BENCH task accuracy."
        ),
    }
    path = output / "summary.json"
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    digest = _sha256(path)
    (output / "summary.sha256").write_text(f"{digest}  summary.json\n")
    print(json.dumps({"accepted": summary["accepted"], "summary": str(path),
                      "sha256": digest}, indent=2))
    return 0 if summary["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
