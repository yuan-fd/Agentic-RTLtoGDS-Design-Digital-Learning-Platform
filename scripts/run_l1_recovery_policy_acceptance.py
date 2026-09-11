#!/usr/bin/env python3
"""Replay typed recovery decisions over pinned real QoR evidence."""

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

from openroad_platform_analysis import classify_convergence  # noqa: E402
from openroad_platform_contracts import (  # noqa: E402
    ConvergenceAssessment, ConvergencePolicy, ConvergenceState,
    DiagnosisReport, EvidencePointer, MetricTrajectory, ObjectiveDirection,
    RecoveryAction, RollbackCheckpoint,
)
from openroad_platform_scheduler import (  # noqa: E402
    L1ControlStateStore, PDAgentControlStateMachine, decide_recovery,
)


CONVERGENCE = ROOT / "var/evidence/evidence-backed-convergence-20260905-r1/summary.json"
CONVERGENCE_SHA = "a1ebfb85c691b5827c130ab7604e0000c9c7bd74448c57d2826a50341bb32d2f"
CLEAN = ROOT / "var/evidence/four-domain-stage-diagnostics-20260905-r1/summary.json"
CLEAN_SHA = "4677856456a0911471f8139f7a5d174c90a3052c3be56679bd01d0b2205ec98e"
BLOCKED = ROOT / "var/evidence/l1-pdagent-control-state-20260905-r1/summary.json"
BLOCKED_SHA = "9360cb95377cd7c1f57e105d95776557337f300a6451a2b482702af82751d158"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reviewed_state(store, goal_id, report, assessment):
    machine = PDAgentControlStateMachine()
    source = EvidencePointer(f"source:{goal_id}", _sha256(CLEAN))
    states = [machine.initialize(goal_id, ("finish",), (source,))]
    states.append(machine.runtime_submitted(
        states[-1], run_id=report.run_id, evidence=report.evidence))
    states.append(machine.runtime_terminal(
        states[-1], terminal_status="succeeded", evidence=report.evidence))
    analyzed, analyzer, debugger = machine.analysis_completed(states[-1], report)
    states.append(analyzed)
    states.append(machine.record_convergence(states[-1], assessment))
    for state in states:
        store.append_planner(state)
    store.append_analyzer(analyzer)
    if debugger is not None:
        store.append_debugger(debugger)
    return states[-1], states, debugger


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("refusing to overwrite recovery-policy evidence")
    expected = ((CONVERGENCE, CONVERGENCE_SHA), (CLEAN, CLEAN_SHA),
                (BLOCKED, BLOCKED_SHA))
    if any(_sha256(path) != digest for path, digest in expected):
        raise ValueError("recovery-policy source evidence drift")
    output.mkdir(parents=True, exist_ok=True)
    convergence = json.loads(CONVERGENCE.read_text())
    clean_report = DiagnosisReport.from_dict(
        json.loads(CLEAN.read_text())["diagnosis_report"])
    blocked_report = DiagnosisReport.from_dict(
        json.loads(BLOCKED.read_text())["diagnosis_report"])
    stalled = ConvergenceAssessment.from_dict(
        convergence["assessments"]["independent_confirmations"])
    unknown = ConvergenceAssessment.from_dict(
        convergence["assessments"]["optimizer_search"])

    store = L1ControlStateStore(output / "control.sqlite")
    stalled_state, stalled_states, _ = _reviewed_state(
        store, "goal-stalled", clean_report, stalled)
    stalled_decision = decide_recovery(
        stalled_state, clean_report, stalled)
    store.append_recovery_decision(stalled_decision)

    blocked_state, blocked_states, _ = _reviewed_state(
        store, "goal-blocked", blocked_report, unknown)
    blocked_decision = decide_recovery(
        blocked_state, blocked_report, unknown)
    store.append_recovery_decision(blocked_decision)

    optimizer = MetricTrajectory.from_dict(
        convergence["trajectories"]["optimizer_search"])
    divergence_trajectory = MetricTrajectory(
        "trajectory-real-regression-tail", optimizer.metric, optimizer.unit,
        ObjectiveDirection.MINIMIZE, optimizer.protocol_sha256,
        optimizer.points[-2:], optimizer.evidence)
    divergence = classify_convergence(
        divergence_trajectory, ConvergencePolicy(
            "rollback-policy-v1", 1e-9, 1e-6, 3, 2, 2))
    rollback_state, rollback_states, _ = _reviewed_state(
        store, "goal-rollback", clean_report, divergence)
    rollback_checkpoint = RollbackCheckpoint(
        "checkpoint-last-clean", rollback_state.goal_id,
        rollback_states[1].planner_state_id, rollback_states[1].revision,
        "finish", 0, divergence_trajectory.points[0].run_id,
        divergence_trajectory.protocol_sha256,
        divergence_trajectory.points[0].evidence)
    rollback_decision = decide_recovery(
        rollback_state, clean_report, divergence,
        rollback_checkpoints=(rollback_checkpoint,))
    store.append_recovery_decision(rollback_decision)

    decisions = (stalled_decision, blocked_decision, rollback_decision)
    checks = {
        "real_stalled_evidence_preserved": stalled.state is ConvergenceState.STALLED,
        "stalled_without_new_authorization_fails_closed":
            stalled_decision.action is RecoveryAction.STOP and
            stalled_decision.reason_code == "stalled_but_l2_authorization_missing",
        "real_blocker_requests_typed_fix":
            blocked_decision.action is RecoveryAction.REQUEST_TYPED_FIX and
            blocked_decision.recovery_class.value == "meso",
        "real_regression_tail_detected": divergence.state is ConvergenceState.DIVERGING,
        "divergence_selects_evidence_checkpoint":
            rollback_decision.action is RecoveryAction.ROLLBACK and
            rollback_decision.rollback_checkpoint_id == rollback_checkpoint.checkpoint_id,
        "all_decisions_durable": all(
            store.get_recovery_decision(item.decision_id) == item for item in decisions),
        "no_shell_or_parameter_payload": all(
            not hasattr(item, "command") and not hasattr(item, "parameters")
            for item in decisions),
        "source_evidence_unchanged": all(
            _sha256(path) == digest for path, digest in expected),
    }
    summary = {
        "schema_version": 1,
        "kind": "l1-typed-recovery-policy-acceptance",
        "accepted": all(checks.values()),
        "sources": [{"source_document": str(path.relative_to(ROOT)),
                     "sha256": digest} for path, digest in expected],
        "scenarios": {
            "stalled_without_new_authorization": {
                "planner_states": [item.to_dict() for item in stalled_states],
                "assessment": stalled.to_dict(),
                "decision": stalled_decision.to_dict(),
            },
            "diagnosed_blocker": {
                "planner_states": [item.to_dict() for item in blocked_states],
                "assessment": unknown.to_dict(),
                "decision": blocked_decision.to_dict(),
            },
            "material_regression": {
                "planner_states": [item.to_dict() for item in rollback_states],
                "assessment": divergence.to_dict(),
                "checkpoint": rollback_checkpoint.to_dict(),
                "decision": rollback_decision.to_dict(),
            },
        },
        "checks": checks,
        "claim_boundary": (
            "Typed, durable policy decisions replayed from real protected evidence. "
            "No retry, fix, rollback, L2 handoff, EDA run, or artifact mutation is "
            "executed. A2 escalation remains denied until a new durable authorization "
            "is verified and consumed by the handoff service."
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
