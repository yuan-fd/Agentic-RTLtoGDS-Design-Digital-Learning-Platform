# Slice 003: Runtime-owned protected evaluator gateway

Status: accepted at the slice boundary and verified on 2026-08-30.

## Intent and boundary

This slice moves the **call site** of the protected ORFS QoR evaluator out of
the ORFS executor and into `WorkflowRuntime`.  It does not change the
evaluator's rules, metrics, parser, benchmark RTL, PDK, SDC/timing target,
toolchain, source lock, statistics, ORFS algorithm, search space, or any
optimizer.

```text
Before
  Runtime -> ORFS adapter -> ORFSRunner -> raw ORFS artifacts
                                      -> common evaluator -> QoR file

After
  Runtime -> ORFS adapter -> ORFSRunner -> raw ORFS artifacts
          -> validate adapter result, paths, hashes and artifact kinds
          -> protected ORFS evaluator -> immutable common_evaluation.json
          -> validate/register evaluator artifact, then record attempt facts
```

The adapter remains the only process bridge to native ORFS.  The evaluator has
no database, scheduler, process-launch, optimizer, benchmark-mutation, or
Runtime-status authority.  Runtime alone records attempt state, hashes,
artifacts and metrics.

## Files changed by this slice

| File | Change |
| --- | --- |
| `packages/contracts/.../protected_evaluation.py` | Added a dependency-free `ProtectedEvaluator` protocol for post-adapter evidence declarations. |
| `packages/contracts/.../__init__.py` | Exposes the protocol without introducing a reverse dependency. |
| `packages/analysis/.../orfs_protected_evaluator.py` | Added the Runtime-invoked ORFS evaluator wrapper.  It calls the unchanged common evaluator, writes an immutable workspace-local JSON result, or writes an explicit error-log artifact. |
| `packages/analysis/.../__init__.py` | Exposes `ORFSProtectedEvaluator`. |
| `packages/execution/.../adapter.py` | Added validation/hashing of post-execution artifacts against the same workspace and manifest allowlists. |
| `packages/execution/.../orfs_runner.py` | Removed the protected-evaluator invocation and its evaluator-artifact collection.  It still produces raw ORFS and pre-existing derived report/evidence files. |
| `packages/scheduler/.../runtime.py` | Injects an optional protected evaluator after successful adapter validation and registers its output with the same Runtime attempt. |
| `apps/api/app.py` | Wires the evaluator into the existing application composition root; no API route or evaluator rule changed. |
| `scripts/run_p2_acceptance.py` | Uses the Runtime-produced evaluation artifact rather than performing a second direct evaluation. |
| `integrations/orfs_agent/source.lock.json`, `integrations/plugins.lock.json` | Marks ORFS-Agent as source-audited but not executable/admitted pending its own native and platform smokes. |
| `tests/test_workflow_runtime.py`, `tests/test_orfs_plugin.py`, `tests/test_l2_external_admission.py` | Adds Runtime ordering/path-safety, infeasible-result, static executor-boundary, and no-auto-admission tests. |

## Semantics and failure handling

1. The adapter must first return `succeeded` and its declared raw artifacts
   must pass path, size, hash and manifest-kind validation.
2. Only then may Runtime call a configured evaluator.
3. A successful evaluation that says `feasible: false` is still canonical
   evidence: the flow ran, but it did not meet the frozen QoR/signoff gate.
   Runtime therefore does not falsely call it a good design.
4. If evaluator input/parsing itself fails, the wrapper writes
   `common_evaluator_error.log` as a registered `report` artifact with
   `official_qor: false`; it never invents metrics or silently passes QoR.
5. Evaluator-produced paths must be relative, inside the attempt workspace,
   non-empty and of a manifest-permitted kind.  An escaped or invalid path
   fails the Runtime attempt rather than being registered.

`ORFSProtectedEvaluator` also rejects an adapter-produced `config_path` that
resolves outside the ORFS implementation workspace.  This prevents a corrupt
plan file from making the protected evaluator read unrelated host data.

## Verification evidence

### Focused tests

The following checks passed without weakening assertions:

```text
python3 -m pytest -q \
  tests/test_workflow_runtime.py \
  tests/test_orfs_plugin.py \
  tests/test_common_evaluator.py \
  tests/test_learning_data.py \
  tests/test_package_architecture_boundaries.py \
  tests/test_runtime_only_worker.py

35 passed in 13.74s
```

The tests prove that Runtime registers a post-execution evaluator artifact and
hash, rejects an evaluator path that escapes the attempt directory, preserves
the no-evaluator path for other plugins, records a fake-ORFS incomplete-signoff
result as `feasible: false`, and that `ORFSRunner` contains neither
`evaluate_orfs_run` nor `_run_common_evaluation`.

`python3 -m compileall` and `git diff --check` also passed.

After the ORFS-Agent registry was fail-closed, its source-lock/admission test
was added and the boundary suite was rerun:

```text
38 passed in 13.75s
```

This confirms the pinned commit is present and BSD-3-Clause is recorded, while
the API has no manifest-registration call for ORFS-Agent before admission.

### Bounded real ORFS smoke

Fresh isolated evidence directory:

```text
var/slice3-protected-evaluator-smoke-20260830-N7kssi/
```

The command was:

```text
python3 scripts/run_p2_acceptance.py \
  --output-root var/slice3-protected-evaluator-smoke-20260830-N7kssi \
  --timeout 7200 --stage-timeout 3600
```

Frozen input: `tests/fixtures/p2_mux_2to1.v`; top `mux_2to1`; platform
`nangate45`; target stage `finish`; seed `1`.  The measured evidence is:

| Evidence | Value |
| --- | --- |
| Runtime run | `41383fe3bbc34c14834194e82b583509` |
| Runtime attempt | `6c97ce04989745c981c0e53ec7227cfd` |
| Terminal status | `succeeded` |
| Wall time | 77.809 s |
| Registered artifacts | 34 |
| Evaluator schema | common evaluator v3 |
| Evaluator ID | `8be6a38f4eb17e75432d69deb979edadf36a0ae00ba9784466695a1f3131bfec` |
| Frozen QoR gate | passed; `feasible: true` |
| Evaluator artifact SHA-256 | `903a9a27bb8610c04d0766524a27a5350ce00df7723afe7b82f091a2d68f5c20` |
| Shared ORFS checkout/toolchain snapshot | unchanged before versus after |

The registered canonical QoR artifact is at:

```text
var/slice3-protected-evaluator-smoke-20260830-N7kssi/attempts/
41383fe3bbc34c14834194e82b583509/6c97ce04989745c981c0e53ec7227cfd/
attempt-1/orfs/implementation/analysis/common_evaluation.json
```

`acceptance_summary.json`, the Runtime database snapshot, adapter request and
result, raw stage logs/JSON, final GDS/DEF/netlist/ODB, plan, input manifest
and toolchain snapshot are retained in the same directory.  This is an
integration smoke only.  It proves the protected-evaluation gateway and
provenance continuity, not a PPA improvement or ORFS-Agent performance claim.

## Protected-component check and rollback

No evaluator rule, benchmark RTL, PDK, SDC, timing objective, seed policy,
statistics protocol, toolchain checkout, ORFS source, or external-plugin
**commit/license** was changed.  The ORFS-Agent admission wording in its lock
was deliberately tightened to fail closed; it does not alter the pinned commit
or grant execution permission.  The real run used a new Runtime workspace and
the recorded before/after snapshot reports the shared toolchain unchanged.

Rollback is a normal Git revert of the listed source/test/composition files.
Do not delete the smoke directory or its Runtime database snapshot: they are
evidence for this migration.  Existing direct runner/research scripts remain
historical/legacy and must not be cited as canonical QoR paths.

## Explicitly not done

This slice is **preparation**, not ORFS-Agent admission.  It does not execute
an ORFS-Agent-to-OpenROAD platform smoke, replace local historical optimizers,
tune a parameter, claim an optimization improvement, or move API/UI code.
ORFS-Agent remains a separate next slice requiring source/commit/license
re-check, native smoke, thin-adapter Runtime smoke through this evaluator, and
an honest claim boundary.

One pre-existing unit test was run during source inspection.  It invokes the
upstream suggestion function with a fake local model response, but does not
invoke OpenROAD or Runtime; it is only a unit-level adapter check and is not
admission evidence.  It created an untracked Python bytecode cache in the
external checkout.  That checkout must therefore be refreshed to a clean,
pinned worktree before the required native smoke; no source file was changed.

During the final intake audit, an existing historical API composition was
found to auto-register the cached ORFS-Agent manifest.  That is an admission
path without the required evidence, so this slice removes the registration and
marks its locks `source-audit-only-pending-native-and-platform-smoke`.  The
adapter/source files remain preserved for the next slice; an API request now
fails closed as “not admitted” rather than launching it.
