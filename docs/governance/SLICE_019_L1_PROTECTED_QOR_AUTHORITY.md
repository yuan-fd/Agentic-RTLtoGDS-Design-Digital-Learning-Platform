# Slice 019 — L1 protected QoR authority

## Intended architectural change

Compose the real ORFS L1 Workbench with `ORFSProtectedEvaluator` and prevent
adapter metrics or adapter-authored metadata from becoming canonical L1 QoR.
Intermediate Runtime metrics remain available to bounded diagnostic queries,
but `DesignState.metrics` is populated only from a Runtime-attested protected
evaluation artifact.

## Files changed

- `apps/l1_workbench/service.py`
- `packages/analysis/src/openroad_platform_analysis/orfs_protected_evaluator.py`
- `packages/scheduler/src/openroad_platform_scheduler/runtime.py`
- `packages/scheduler/src/openroad_platform_scheduler/l1_runtime_bridge.py`
- `tests/test_l1_workbench_evaluator.py`
- `tests/test_l1_runtime_bridge.py`
- `tests/test_runtime_protected_evaluator.py`
- `tests/test_orfs_plugin.py`
- this evidence record

## Before and after dependency edge

Before: Workbench constructed `WorkflowRuntime` without a protected evaluator,
and the L1 bridge copied every adapter metric into authoritative DesignState.

After: the ORFS Workbench injects the protected evaluator. Runtime rejects an
adapter that claims reserved protected-evaluator metadata, stamps artifacts
returned through its protected evaluator port, and persists canonical metrics
with the artifact. The L1 bridge accepts only one such stamped artifact and
binds its state evidence to the registered artifact SHA-256. No official
artifact means an empty canonical metric map, not adapter-derived QoR.

## Acceptance evidence

Focused tests cover composition, metadata spoof rejection, absence of
canonical metrics without evaluator evidence, successful promotion from a
Runtime-attested evaluator artifact, evaluator workspace confinement, and a
real ORFS Runtime evaluator invocation. The smoke backend remains importable
without the optional analysis package on its minimal server `PYTHONPATH`.

## Protected components and unrelated behavior

No evaluator rule, benchmark, RTL, PDK, SDC, parser threshold, or ORFS input
was relaxed or changed. The evaluator adds the already-derived numeric values
to its registered metadata; the immutable JSON evaluation remains the source
evidence. L2 controller and campaign logic are outside this slice.

## Rollback

Revert only the files listed above. Do not change or delete recorded Runtime
workspaces. Rollback would restore adapter metrics as L1 state and therefore
must not be used for product QoR claims.
