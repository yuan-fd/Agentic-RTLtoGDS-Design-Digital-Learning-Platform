# Slice 039: durable A2-ORFO feedback controller

## Boundary

This slice adds a restartable A2-ORFO campaign controller. It does not yet
change the public product allowlist or Workbench/API route, and it does not
modify the old completed ORFS-Agent campaign.

## Ownership and flow

```text
durable L2 authorization/checkpoint
  -> pinned A2-ORFO policy Runtime task
  -> complete 12-D candidate artifact
  -> ORFS-Agent candidate Runtime task
  -> protected evaluator
  -> success/failure feedback retained
  -> pinned A2-ORFO feedback Runtime task
  -> next candidate + A2 checkpoint
  -> optional independent confirmations
```

A2-ORFO owns proposal generation. ORFS-Agent remains the executor because the
admitted A2 repository delegates physical implementation to ORFS. Runtime is
the lifecycle authority and the protected evaluator is the measurement
authority. No local BO/GP algorithm is introduced.

The controller freezes both domains, all 12 parameters, variable-clock
semantics, objective, initial evidence, optimizer/OR/confirmation seeds,
feedback count, suggestion count, EDA budget, and parallelism. Every state
transition uses optimistic durable revisions and every TaskSpec has a stable
pipeline-derived ID, so restart does not duplicate submission. Failed
candidates remain in `measured_observations` and are fed back to A2.

## Changed files

- `packages/execution/src/openroad_platform_execution/a2_orfo_plugin.py`
- `packages/scheduler/src/openroad_platform_scheduler/a2_orfo_campaign.py`
- `packages/scheduler/src/openroad_platform_scheduler/__init__.py`
- `tests/test_a2_orfo_campaign.py`
- `scripts/run_a2_orfo_durable_controller_acceptance.py`
- this record

## Tests and real bounded acceptance

Focused tests cover the policy→candidate→feedback→next-candidate path,
failure retention, optional confirmation, mid-loop service reconstruction,
idempotent TaskSpec IDs, full 12-D preservation, parallelism/budget checks and
configuration drift rejection.

The real acceptance consumes, in read-only replay mode, the already executed
single-feedback Runtime evidence from Slice 030. It reconstructs the service
on every transition and verifies the exact A2 candidate, protected evaluator
feedback, and next A2 candidate. The source Runtime database is hash-pinned
before and after replay.

```text
var/evidence/a2-orfo-durable-controller-20260905-r1/summary.json
```

This is controller/restart acceptance plus the prior real execution smoke; it
is not a full A2 campaign or PPA-superiority result.

## Protected and unrelated behavior

No source campaign, Runtime database, evaluator, RTL, PDK, SDC, search-space
bound, plugin source, old product route, or external campaign changes.

## Rollback

Remove the A2 controller, its scheduler exports, domain deserializer, tests,
acceptance script and this record. Preserve its SQLite evidence. The existing
ORFS-Agent product route remains unaffected until the next migration slice.
