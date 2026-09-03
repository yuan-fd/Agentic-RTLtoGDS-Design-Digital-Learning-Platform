# Slice 011: ORFS-Agent execution-envelope protocol

Status: implemented and verified; new formal campaign started separately.

## Intent

Slice 010 proved that the completed v1 one-factor feasibility report has only
32 repeatedly verified coordinate combinations.  The requested ORFS-Agent
shape needs 301 distinct screening coordinates.  This slice adds a narrowly
defined candidate-envelope contract.  It does not change ORFS-Agent GP/EI,
Runtime, benchmark inputs, toolchain, resource policy, protected evaluator or
the completed preflight.

## Before and after

| Concern | Before | After |
| --- | --- | --- |
| Candidate values | Only discrete values individually replicated-feasible in the one-factor report | The same values remain `verified_values`; an explicit finite interpolation of `place_density_lb_addon` may be submitted to the evaluator as `execution_values`. |
| Claim | The report correctly disclaimed arbitrary-combination feasibility, but the formal runner treated it as a 301-point feasible catalogue | The new object says it is an execution envelope.  Interpolated values are never called preflight-feasible. |
| Failure handling | A 32-point capacity caused a fail-closed pre-formal stop | Formal screening preserves terminal failures.  It may fail honestly if fewer than 12 distinct warm-up points are evaluator-feasible. |
| Fairness | No formal arm could start | Both GP/EI and fixed-seed Random use the same envelope digest, report digest, evaluator, budget, seed policy and resource policy. |

## Bounded implementation

- `target_feasibility.py` adds
  `derive_target_execution_envelope`.  It first validates the immutable v1
  report, retains `verified_values`, and accepts only declared, finite Decimal
  grid steps that exactly tile a verified numeric interval.
- The Sky130HD/AES campaign declares one grid only:
  `place_density_lb_addon = 0.4250..0.4936` at `0.0001`.  With the other four
  two-valued verified dimensions, the typed legal capacity is 10,992.  This
  is capacity for protected measurements, not a guarantee that every point is
  feasible.
- The scheduler recognizes
  `target_execution_envelope_external_l2_v3` only if the envelope includes a
  versioned kind and separately stored verified-value evidence.
- The systemd sequencer can reuse only a completed, SHA-verified preflight
  root, while requiring fresh supervisor, formal, control and aggregate output
  paths.  It still executes `formal -> equal-budget control -> aggregate` in
  one `KillMode=control-group` lifecycle.

## Evidence and verification

The completed source report is:

```text
var/orfs-agent-target-feasibility-20260831-systemd-v3-7200/
report SHA-256: 71522b0680ecbfdbb42eb40ab5eccafcb43b45a36f68278622a5a3f985bc89eb
```

Focused verification after this change:

```text
32 passed
tests/test_target_feasibility.py
tests/test_orfs_agent_systemd_campaign.py
tests/test_external_l2_service.py
tests/test_orfs_agent_plugin.py
tests/test_orfs_agent_equal_budget_aggregation.py
tests/test_l2_external_admission.py
tests/test_seeded_random_control_plugin.py
```

The new campaign is rooted at:

```text
var/orfs-agent-formal-supervisor-20260831-v4-execution-envelope-7200/
```

with new agent/control/aggregate output paths bearing the same
`v4-execution-envelope-7200` identity.  It is an adapted platform experiment,
not an exact numerical reproduction of the upstream paper.

## Rollback

No historical result is modified.  A rollback is a normal Git revert of this
slice's analysis, scheduler, supervisor and test changes.  It does not delete
the v3 completed preflight, the v3 capacity-stop evidence, or any v4 Runtime
artifact.  If the v4 campaign itself fails, retain its complete evidence and
do not widen this envelope in place.
