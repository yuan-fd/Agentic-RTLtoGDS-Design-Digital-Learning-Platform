# Slice 027 — shared-filesystem Runtime durability

## Problem

The first complete 78-measurement worker crashed while four Runtime attempts
were committing concurrently. `runtime.sqlite` reported `database disk image
is malformed`. The state root is on `fuse.glusterfs`, while Runtime and the L2
checkpoint store selected SQLite WAL.

## Evidence

- failed worker stack: `RuntimeStore.finish_attempt -> _event ->
  sqlite3.DatabaseError`;
- corrupt database SHA-256:
  `0bc6b827176d269b176fe2a9b06ce1fbd392678203ef0cb14fb856c951ef2dcc`;
- both the live corrupt files and their first-read copies are retained under
  `var/evidence/l1-aes-to-full-l2-handoff-20260904-r2/campaign-runtime-db-corruption`;
- SQLite `.recover` produced a database with 53 runs, 37 attempts, 170
  artifacts, 8 metrics, and 409 pre-recovery events; `PRAGMA quick_check`
  returned `ok`;
- the four incomplete leases were expired as `lost`, causing their one-attempt
  runs to terminate as failed; sixteen never-started runs were cancelled with
  normal Runtime events.

## Why the current plan fails

WAL coordinates readers through a shared-memory file and is not supported on
network filesystems. More retries would expose the same persistence defect and
could destroy the sole experiment ledger. Reducing `max_parallel` would evade
the advertised complete ORFS-Agent parallel campaign and would not make WAL a
valid shared-filesystem format.

## Options

- Option A: move only this acceptance database to local scratch. This hides a
  deployment constraint and leaves durable state outside the evidence root.
- Option B: use SQLite's rollback journal for shared-filesystem portability and
  serialize the Runtime authority's short write transactions within its
  process, while keeping EDA subprocesses parallel.

## Recommendation and implemented boundary

Option B is implemented. Runtime EDA execution remains four-way parallel; only
transaction commits pass through one re-entrant lock. Runtime and durable L2
checkpoints now select `journal_mode=DELETE`, `synchronous=FULL`, and a 30 s
busy timeout.

Changed files:

- `packages/scheduler/src/openroad_platform_scheduler/runtime_store.py`
- `packages/scheduler/src/openroad_platform_scheduler/pipeline_checkpoint.py`
- `tests/test_runtime_store.py`
- `tests/test_pipeline_checkpoint.py`
- this record

Before: `parallel Runtime threads -> independent WAL writers -> GlusterFS
shared-memory files`.

After: `parallel EDA -> RuntimeStore write lock -> rollback-journal commit`,
with the checkpoint controller using the same portable journal mode.

No TaskSpec, plugin, candidate, evaluator, RTL, PDK, SDC, toolchain, objective,
or measurement budget changed.

## Acceptance

The focused suite was repeated five times for the 64-run/8-thread Runtime
stress test, then exercised with the campaign and adapter tests. Latest joint
result:

```text
21 passed in 2.18s
```

The recovered r2 Runtime database now reports `PRAGMA journal_mode=delete` and
`PRAGMA quick_check=ok`.

The deployment-filesystem smoke is retained at
`var/evidence/runtime-shared-fs-integrity-20260904-r1`: 256 unique runs were
submitted, started, and completed through eight concurrent writers on
`fuse.glusterfs`; all 256 succeeded, all 1,280 events remained readable, and
`quick_check=ok`. Summary SHA-256:
`77fd33f4be657558aa0a0afdf27a7599389781bb295034ed7b402144a01dc45b`.
The preceding harness-only PYTHONPATH error is retained as r0 and created no
Runtime row.

## Rollback

Revert the four implementation/test files. Restore the exact corrupt r2 files
from `campaign-runtime-db-corruption` only for forensic reproduction; do not
resume execution against them. No external source or protected component needs
rollback.
