# L1-B2: artifact reads, selected stage, and observed-run budget

Status: accepted implementation slice (2026-09-03)

## Boundary

Complete the remaining Tutorial L1 execution primitives required before a
planner loop: a bounded artifact excerpt, a policy-allowed `run_stage`, and
budget consumption only after a Runtime terminal observation.

```text
before: full-flow only; a run observation did not consume L1 EDA budget
after:  artifact kind -> Runtime registry -> excerpt receipt
        allowed stage -> stage-specific TaskSpec -> Runtime -> observed state
        every observed run -> canonical reducer decrements remaining budget
```

No UI, evaluator, ORFS adapter implementation, RTL, SDC, PDK, or toolchain
source changed.

## Safety rules

- The artifact API accepts only an approved artifact kind (`report`, `log`,
  `run_result`, `config`); it resolves an artifact ID from the current
  Goal-owned Runtime run. No path enters L1 transport.
- `run_stage` creates a TaskSpec whose `target_stage` already equals the
  validated stage, preventing full-flow artifact expectations from being
  attached to a partial stage run.
- Runtime terminal observation is the only point at which `max_eda_runs`
  changes. Query calls do not consume EDA-run budget.

## Changed files

- `apps/l1_workbench/service.py`
- `apps/l1_workbench/server.py`
- `packages/scheduler/.../l1_loop.py`
- `packages/scheduler/.../l1_runtime_bridge.py`
- `packages/scheduler/.../l1_state_reducer.py`
- `packages/scheduler/.../l1_trace_service.py`
- `packages/scheduler/.../l1_trace_store.py`
- `tests/test_l1_workbench_api.py`
- `tests/test_l1_runtime_bridge.py`

## Acceptance evidence

Focused tests: `28 passed` across Workbench API, durable loop, Runtime bridge,
trace service and tutorial profile tests.

Real bounded ORFS evidence root:

```text
/tmp/openroad-l1-b2-real-20260903
```

It records one Goal with budget three, a successful `finish` baseline, typed
timing/DRC/congestion/metrics queries, a bounded registered report excerpt,
then a successful `route` stage run.  Runtime observations reduced the state
budget from `3` to `2` to `1`; raw Runtime artifacts remain in the two
attempt-local workspaces under that evidence root.

## Rollback

Revert this slice commit.  Do not remove the evidence root or historical trace
records.  No schema migration or protected component rollback is needed.
