# Slice 038: typed recovery, rollback and A2 escalation policy

## Boundary

This slice turns a persisted `DiagnosisReport` and `ConvergenceAssessment`
into one durable typed policy decision. It does not execute retry, repair,
rollback or optimization, change Runtime, or migrate the product L2 entry.

## Policy

- Only explicitly classified transient infrastructure failure may consume a
  micro retry budget.
- An evidence-backed blocker requests a typed meso fix; it never emits shell.
- Consecutive material regression selects the latest same-goal clean
  checkpoint and consumes macro rollback budget.
- A stalled clean trajectory may target `a2-orfo` only when an explicit
  `L2HandoffAuthorization` is present. The existing handoff service must still
  verify and consume its durable trace receipt.
- Missing authorization, evidence, checkpoint or budget fails closed.
- Improving or inconclusive clean evidence continues gathering evidence; L1
  does not invent a search algorithm.

The Planner now records the exact convergence assessment ID. Recovery
decisions are append-only rows in the L1 control database.

## Changed files

- `packages/contracts/src/openroad_platform_contracts/l1_control_state.py`
- `packages/contracts/src/openroad_platform_contracts/recovery.py`
- `packages/contracts/src/openroad_platform_contracts/__init__.py`
- `packages/scheduler/src/openroad_platform_scheduler/l1_control_state_machine.py`
- `packages/scheduler/src/openroad_platform_scheduler/l1_recovery_policy.py`
- `packages/scheduler/src/openroad_platform_scheduler/__init__.py`
- `tests/test_l1_recovery_policy.py`
- `scripts/run_l1_recovery_policy_acceptance.py`
- this record

## Tests and real bounded acceptance

Focused tests cover divergence rollback, blocker-to-typed-fix, transient-only
retry, exhausted budgets, foreign-goal checkpoint rejection, durable decision
round trips, and fail-closed/authorized A2 proposals.

The real acceptance replays three pinned cases: stable independent ORFS
confirmations without a fresh authorization, a protected timing blocker, and
a material ECP regression with a clean artifact-backed checkpoint.

```text
var/evidence/l1-typed-recovery-policy-20260905-r1/summary.json
```

The exact summary hash and acceptance status are written after execution.

## Protected and unrelated behavior

All source summaries are hash-pinned before and after replay. No source
campaign, Runtime state, evaluator, RTL, PDK, SDC, search space, plugin, or
product allowlist changes.

## Rollback

Remove the recovery contract/policy, their exports, tests, acceptance script
and this record; remove the optional Planner assessment field and `continue`
enum member only after confirming no newer checkpoint uses them. Preserve all
SQLite evidence as historical evidence.
