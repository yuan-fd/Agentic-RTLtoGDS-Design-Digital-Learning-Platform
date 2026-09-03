# Slice 012: ORFS-Agent progress-telemetry isolation

Status: implemented and focused-test verified; a replacement experiment must
start in a new output root.

## Problem

The v4 formal controller stopped while warm-up work was active.  At the same
timestamp (`2026-08-31T07:36:26Z`), eight live ORFS adapter processes wrote
`BrokenPipeError` result files, while their Runtime attempts were left in
`running`.  Seven earlier warm-ups and all three baseline replicas had already
completed successfully.  The v4 output is therefore incomplete and is not an
optimizer result.

The supervisor had no durable lifecycle receipt and its configured append log
is empty.  Systemd reports only that its worker exited with code 1.  Available
system and cgroup checks contain no readable OOM event.  These facts do not
prove the initiating external signal or controller exception.

One concrete unsafe dependency was present in the process boundary: every
OpenROAD progress line synchronously invoked Runtime/UI observer code.  An
observer exception (for example, an SQLite lock) was intentionally re-raised
by `ProcessGuardian`; that killed the child process tree.  This can turn a
non-authoritative status/event write into loss of a protected EDA evaluation.

## Change boundary

Only the execution-lifecycle boundary changed:

- `ProcessGuardian` preserves an observer exception in the raw adapter log
  (`[guardian] progress observer failed: ...`) and continues supervising the
  tool process.  Timeout, explicit cancellation, SIGINT and SIGTERM retain
  their previous process-tree cleanup behavior.
- The systemd sequencer now sets unbounded start/runtime limits explicitly and
  writes an atomic `supervisor-receipt.json` before and after each controller
  phase.  A non-zero formal, control or aggregation subprocess is still a
  failed, fail-closed result; no output is promoted or retried automatically.

No RTL, SDC, PDK, ORFS/ORFS-Agent source, toolchain, evaluator, search domain,
seed policy, budget, objective, or candidate algorithm changed.

## Verification

```text
28 passed
tests/test_process_guardian.py
tests/test_orfs_agent_systemd_campaign.py
tests/test_external_l2_service.py
tests/test_orfs_agent_plugin.py
tests/test_l2_external_admission.py
tests/test_orfs_agent_equal_budget_aggregation.py
```

The added regression intentionally makes the progress callback throw.  The
subprocess must finish with exit code zero and the log must retain the observer
error; this verifies that telemetry cannot falsely cancel a successful tool.

## Recovery and rollback

The v4 root remains historical incomplete evidence.  Its `running` attempts
are not reclassified as successes and no old run is retried in place: their
frozen `max_attempts=1` contract makes resumption invalid.  The successor must
use fresh formal/control/aggregate roots and repeat the entire paired protocol.

Rollback is a Git revert of this slice's two implementation files and tests.
It does not delete v4 evidence or change the interpretation of its failed
lifecycle.
