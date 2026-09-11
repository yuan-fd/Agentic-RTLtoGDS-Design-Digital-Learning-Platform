"""Policy admission for selecting an already verified RTL checkpoint."""

from __future__ import annotations

from typing import Any, Mapping
from uuid import uuid4

from openroad_platform_contracts import (
    EvidencePointer, RTLCandidate, RecoveryAction, RecoveryDecision,
    RollbackCheckpoint, RTLCheckpointRestorePlan,
)


def plan_rtl_checkpoint_restore(
    decision: RecoveryDecision,
    checkpoint: RollbackCheckpoint,
    lineage: Mapping[str, Any],
    *,
    failed_candidate_id: str,
    target_candidate_id: str,
) -> RTLCheckpointRestorePlan:
    """Admit one content-addressed ancestor after an L1 recovery decision."""
    decision.validate()
    checkpoint.validate()
    if decision.action not in {
        RecoveryAction.REQUEST_TYPED_FIX, RecoveryAction.ROLLBACK,
    }:
        raise ValueError("RTL checkpoint restore requires a fix or rollback decision")
    if (decision.action is RecoveryAction.ROLLBACK
            and decision.rollback_checkpoint_id != checkpoint.checkpoint_id):
        raise ValueError("rollback decision does not select this checkpoint")
    if checkpoint.goal_id == "" or checkpoint.planner_state_id == "":
        raise ValueError("RTL checkpoint is incomplete")
    candidates = {
        str(item.get("candidate_id")): RTLCandidate.from_dict(item)
        for item in lineage.get("candidates", ())
    }
    try:
        failed = candidates[failed_candidate_id]
        target = candidates[target_candidate_id]
    except KeyError as exc:
        raise ValueError("RTL restore candidate is not registered") from exc
    if target_candidate_id not in failed.parent_candidate_ids:
        raise ValueError("RTL restore target is not a direct candidate ancestor")
    target_sha = _candidate_sha(target)
    target_pointer = EvidencePointer(
        f"artifact:rtl-candidate:{target_sha}", target_sha)
    if target_pointer not in checkpoint.evidence:
        raise ValueError("RTL checkpoint does not bind the target candidate artifact")
    checks = [item for item in lineage.get("checks", ())
              if item.get("candidate_id") == target_candidate_id
              and item.get("status") == "passed"]
    compile_checks = [item for item in checks
                      if item.get("check_kind") == "compile_lint"]
    functional_checks = [item for item in checks if item.get("check_kind") in {
        "simulation", "formal", "equivalence",
    }]
    if not compile_checks or not functional_checks:
        raise ValueError("RTL restore target lacks independent verification gates")
    if str(compile_checks[-1].get("detail", {}).get("run_id") or "") != checkpoint.run_id:
        raise ValueError("RTL checkpoint run does not match target verification")
    check_evidence = tuple(EvidencePointer(
        str(item["evidence_ref"]), str(item["evidence_sha256"]))
        for item in (compile_checks[-1], functional_checks[-1]))
    plan = RTLCheckpointRestorePlan(
        plan_id=f"rtl-restore-{uuid4().hex}",
        recovery_decision_id=decision.decision_id,
        checkpoint_id=checkpoint.checkpoint_id,
        failed_candidate_id=failed_candidate_id,
        target_candidate_id=target_candidate_id,
        target_rtl_sha256=target_sha,
        evidence=tuple(dict.fromkeys((
            *decision.evidence, *checkpoint.evidence, target_pointer,
            *check_evidence,
        ))),
    )
    plan.validate()
    return plan


def select_rtl_checkpoint_candidate(
    plan: RTLCheckpointRestorePlan,
    lineage: Mapping[str, Any],
) -> RTLCandidate:
    """Resolve the plan to one immutable candidate; no file or process action."""
    plan.validate()
    target = next((RTLCandidate.from_dict(item)
                   for item in lineage.get("candidates", ())
                   if item.get("candidate_id") == plan.target_candidate_id), None)
    if target is None or _candidate_sha(target) != plan.target_rtl_sha256:
        raise ValueError("RTL restore target is missing or content identity changed")
    return target


def _candidate_sha(candidate: RTLCandidate) -> str:
    prefix = "artifact:rtl-candidate:"
    if not candidate.rtl_artifact_ref.startswith(prefix):
        raise ValueError("RTL restore target is not content addressed")
    value = candidate.rtl_artifact_ref.removeprefix(prefix)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("RTL restore target SHA-256 is invalid")
    return value
