# Slice 002: Runtime-only legacy Worker

Status: accepted at the slice boundary and verified on 2026-08-30.

## Intent and boundary

This slice retires the direct execution edge from the old durable queue
Worker to `ORFSRunner`.  It does not replace ORFS, tune a search algorithm,
change a benchmark, alter RTL/SDC/PDK, modify protected evaluation, move an
HTTP route, or delete the historical queue.

```text
Before
  JobStore -> Worker -> ORFSRunner -> ORFS

After
  JobStore -> Worker (compatibility driver)
                  -> WorkflowRuntime -> PluginRegistry -> ProcessAdapter
                     -> admitted ORFS adapter -> ORFSRunner
```

After a legacy job is bound, `RuntimeStore` is the only authority for run,
stage, attempt, workspace, lease, cancellation enforcement, raw artifacts,
metrics and terminal status.  `JobStore` retains only the pre-existing queue
entry, a `runtime_run_id` back-reference, an incoming legacy cancellation
request, and a terminal read-model projection for historical clients.

## Files changed by this slice

| File | Change |
| --- | --- |
| `packages/scheduler/.../worker.py` | Replaced direct `ORFSRunner` construction and stage callbacks with an injected `WorkflowRuntime` plus generic `RTLToGDSFactory`. |
| `packages/scheduler/.../runtime.py` | Added narrowly documented idempotent submission for crash-safe legacy rebinding and an external cancellation intake hook that records cancellation in `RuntimeStore` before process termination. |
| `packages/scheduler/.../store.py` | Added an additive `runtime_run_id` column and a one-way terminal Runtime projection.  It does not store attempts or artifacts as authority. |
| `packages/scheduler/.../cli.py` | Makes the historical `openroad-jobs worker` command an explicit compatibility composition root which builds Runtime, registry and factory. |
| `tests/test_runtime_only_worker.py` | New success, live cancellation and static-boundary tests. |
| `tests/test_workflow_runtime.py` | Idempotent-submission test. |

No ORFS source/adapter algorithm, benchmark RTL, PDK, SDC, evaluator,
statistics protocol, external source lock, or API/UI route was edited in this
slice.

## Compatibility lifecycle

1. A historical Job is claimed as before.  A cancellation before Runtime
   admission remains a legacy-only cancellation and no Runtime run is made.
2. Worker translates the validated old `RunRequest` through the injected
   RTL-to-GDS capability factory.  Its stable task id is `legacy:<job-id>`.
3. `WorkflowRuntime.submit_idempotent()` returns an already-admitted identical
   task after a Worker restart, instead of making a second attempt/run.
4. JobStore records exactly one immutable `runtime_run_id`; rebinding it to a
   different run is rejected.
5. Worker calls `WorkflowRuntime.execute_once()`.  ORFS starts only inside the
   registered adapter subprocess.  Runtime records tool-stage events,
   attempt state, artifacts and metrics.
6. A legacy cancellation is observed by Runtime, persisted as
   `run.cancel_requested`, then enforced by its normal process guardian.  The
   old job sees only the eventual Runtime terminal projection.
7. The old result JSON is a pointer-rich Runtime snapshot for read
   compatibility.  It is not a second artifact/metric store.

## Verification evidence

### Focused tests

The following focused suite passed without weakening assertions:

```text
python3 -m pytest -q \
  tests/test_runtime_only_worker.py \
  tests/test_workflow_runtime.py \
  tests/test_scheduler.py \
  tests/test_legacy_projection.py \
  tests/test_package_architecture_boundaries.py

15 passed in 3.44s
```

The new tests prove all three migration properties:

- Worker source has no `openroad_platform_execution` import and no
  `ORFSRunner` identifier.
- One legacy job produces one Runtime run/attempt, and its Runtime-validated
  artifact is visible through the non-authoritative legacy projection.
- A live legacy cancellation becomes a Runtime cancellation and is then
  projected as `cancelled`.

`python3 -m compileall` and `git diff --check` also passed.

### Bounded real ORFS smoke

Fresh output directory:

```text
var/slice2-runtime-worker-smoke-20260830-DJG1IA/
```

Entry path used the historical command line queue, not direct Runtime
submission:

```text
openroad-jobs submit p2_mux_2to1.v
openroad-jobs worker --once
```

Frozen input: `tests/fixtures/p2_mux_2to1.v`; top `mux_2to1`; platform
`nangate45`; target `finish`; seed `1`.  The actual IDs are:

| Evidence | Value |
| --- | --- |
| Legacy Job | `e01e5666038c41dea47150234921f961` |
| Runtime run | `cdea49da8f124e66b34402cbb26088bc` |
| Runtime attempt | `5ad03b7e82ec438f8d0c73a331ec54f8` |
| Terminal status | `succeeded` |
| Validated Runtime artifacts | 34, including final GDS/DEF/netlist/ODB/configuration/raw reports |
| Protected evaluator | common evaluator schema v3; feasible |
| Evaluator id | `2717a789487d9ea965fea4ab841a5ce716d5a078b46f0bc1faafa551ed1911da` |

The raw Runtime database, old queue database, adapter request/result/log,
ORFS `run_result.json`, GDS, and evaluator output are retained below that
directory.  `slice2_smoke_summary.json` is a concise index.  This is an
integration smoke only: it demonstrates Runtime ownership and artifact/eval
continuity; it makes no PPA-improvement claim.

## Protected components and rollback

The changed file set contains no protected benchmark, RTL, PDK, SDC,
toolchain, evaluator, protocol or statistic implementation.  The smoke used
a new isolated workspace and SQLite files under `var/`; it did not modify the
shared ORFS checkout.  Raw source/input hashes and toolchain snapshot are
present in its Runtime artifacts.

Rollback is a normal Git revert of the six source/test files listed above.
The extra nullable `jobs.runtime_run_id` column is additive and ignored by the
old code, so it is intentionally left in place on rollback.  Do not delete
the smoke directory or legacy rows: they are migration evidence.

## Explicitly not done

This is not Slice 3.  API extraction, runtime/package renaming, evaluator
refactoring, optimizer replacement, UI changes, and deletion of the old
queue remain outside this accepted boundary.
