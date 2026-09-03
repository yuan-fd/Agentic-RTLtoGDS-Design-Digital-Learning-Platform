# L1-B1: Runtime-backed L1 queries

Status: accepted implementation slice (2026-09-03)

## Boundary

Expose a narrowly bounded read path from a finalized/observed L1 Session to
the existing Runtime bridge.  This slice adds no EDA process, parser,
optimizer, evaluator, filesystem endpoint, or user-selected Runtime ID.

```text
before: Workbench could submit a full flow but could not ask typed questions
after:  observed DesignState run_id -> typed query -> Policy -> Runtime view -> receipt/trace
```

The API accepts one named query kind (`timing`, `congestion`, `drc`, `power`,
or `metrics`) and a bounded limit.  It derives the run ID only from the
current state's `runtime_run_id`; direct paths and arbitrary run IDs never
cross the transport boundary.

## Changed files

- `apps/l1_workbench/service.py`
- `apps/l1_workbench/server.py`
- `tests/test_l1_workbench_api.py`

## Acceptance

`POST /api/l1/sessions/{id}/queries` after a real Runtime-backed baseline
returns a completed `query_timing` receipt referencing the same run ID.  The
focused suite passed:

```text
23 passed
tests/test_l1_workbench_api.py
tests/test_l1_tutorial_profile.py
tests/test_l1_runtime_bridge.py
tests/test_l1_durable_loop.py
```

The test proves the trace contains the query's tool-call, allowed Policy
decision and receipt.  It is a bounded Runtime control-plane smoke; the next
slice will run the full query set against the real ORFS artifact set.

## Rollback

Revert this slice commit.  Existing trace receipts remain audit history; no
database schema, Runtime, ORFS adapter, evaluator, RTL, SDC or toolchain data
needs migration.
