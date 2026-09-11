# Slice 040: native A2-ORFO bootstrap

## Boundary and stop resolution

**Problem.** The admitted A2 policy required four prior successful
measurements, so a new product campaign could not start without importing
historical ORFS-Agent data.

**Evidence.** The pinned A2-ORFO source exposes
`OptimizationWorkflow.generate_initial_parameters(num_runs)` and its native
12-D constraints. The former adapter exposed only `run_iteration`.

**Why the prior plan fails.** Product migration with a historical-data
prerequisite would not be a complete new-user path and could compare
incompatible design/protocol evidence.

**Option A.** Invent a local sampler.

**Option B.** Admit the upstream initializer as a separate typed Runtime
capability and have the durable controller measure every generated point.

**Recommendation.** Option B, consistent with `Reuse > Adapt > Reimplement`.

This slice adds `optimizer.l2.a2-orfo-initialize`; it does not yet change the
public product allowlist or Workbench route.

## Flow and safety

The adapter invokes the exact pinned upstream initializer in an attempt-private
copy with the published 12-D domain bound before generation. It makes no model
call, runs no EDA, and emits only candidate artifacts. The controller submits
all bootstrap candidates to ORFS-Agent/Runtime, retains failures, and begins
A2 policy fitting only after the frozen minimum successful measurement count
is present. Insufficient bootstrap success ends in `diagnosis_required`.

## Changed files

- `packages/execution/src/openroad_platform_execution/a2_orfo_plugin.py`
- `packages/execution/src/openroad_platform_execution/__init__.py`
- `integrations/a2_orfo/a2_orfo_adapter.py`
- `packages/scheduler/src/openroad_platform_scheduler/a2_orfo_campaign.py`
- `tests/test_a2_orfo_plugin.py`
- `tests/test_a2_orfo_campaign.py`
- `scripts/run_a2_orfo_native_initializer_acceptance.py`
- this record

## Tests and real bounded acceptance

Tests cover an empty-history bootstrap, full Runtime measurement routing,
minimum-success gating, complete 12-D candidates, and the existing native
policy path. A real Runtime smoke executes the upstream initializer:

```text
var/evidence/a2-orfo-native-initializer-20260905-r1/summary.json
```

This proves native candidate generation, not ORFS execution or PPA quality;
real ORFS/evaluator feedback remains proven by Slice 030.

## Protected and unrelated behavior

No evaluator, RTL, PDK, SDC, objective baseline, external source, old campaign
or product role changes. Bootstrap context exists only inside the isolated
adapter attempt; protected execution inputs stay protocol-bound.

## Rollback

Remove the initializer task/capability and adapter branch, restore the
controller's prior-evidence requirement, and remove the focused tests, script
and this record. Preserve generated evidence as historical evidence.
