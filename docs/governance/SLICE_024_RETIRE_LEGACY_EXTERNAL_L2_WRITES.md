# Slice 024 — retire legacy external-L2 writes

## Intended architectural change

Fail closed every product write into the historical
`external-orfs-agent-loop-v1` controller. That controller projects the
optimizer into the former fixed-clock, reduced-domain protocol and therefore
must not coexist as an executable alternative to the complete upstream
12-dimensional, variable-clock ORFS-Agent path.

Historical checkpoints and the scheduler implementation remain readable for
provenance and reproduction. The legacy Web surface may render those stored
facts, but may not create, advance, resume, or describe a checkpoint as an
active product campaign.

## File boundary

- `apps/api/app.py`
- `apps/web/index.html`
- `apps/web/assets/app.js`
- API/Web retirement tests
- product and operations documentation that currently calls the route active
- `docs/governance/LEGACY_CLEANUP_INVENTORY.md`
- this evidence record

No Runtime, evaluator, ORFS adapter, upstream optimizer, L1 Workbench, or
complete L2 campaign implementation is in this slice.

## Before and after dependency edge

Before: legacy Web or an in-process caller -> `ApiState` -> historical
reduced-domain `ExternalOptimizerLoopService` -> Runtime.

After: legacy Web -> owner-scoped GET of stored historical checkpoints only.
All API/service create and advance calls terminate before design resolution,
plugin lookup, task construction, controller mutation, or Runtime submission.
The executable L2 edge remains L1 authorized handoff -> full-campaign
controller -> upstream ORFS-Agent plugin -> Runtime/protected evaluator.

## Acceptance evidence

Focused tests:

```text
30 passed in 14.42s
```

The authenticated HTTP test proves:

- create returns HTTP 400 with the retirement boundary;
- advance returns HTTP 400 with the historical read-only boundary; and
- owner-scoped historical listing remains HTTP 200.

The in-process test replaces design resolution and controller construction
with sentinels, invokes both legacy writes, and proves neither sentinel was
reached. The Web source test proves there is no POST call to the retired route
and the remaining display is explicitly historical/read-only. Scheduler-level
`ExternalOptimizerLoopService` tests remain green because its source and
checkpoint decoder are retained for historical evidence.

Evidence:

- `var/evidence/legacy-external-l2-retirement-20260904-r1`
- summary SHA-256:
  `adb86538a6240ba4b724a331b0f953afea0da95ea864f72bd27cbf13bece3f90`
- Runtime runs created: `0`
- historical checkpoints deleted: `0`

## Protected components and unrelated behavior

No RTL, PDK, SDC, evaluator, campaign budget, parameter domain, external
checkout, artifact, or historical checkpoint is changed or deleted.

## Rollback

Revert only the listed API/Web/tests/docs files. A rollback would reopen an
architecturally invalid L2 write path and must not be presented as restoring
complete ORFS-Agent functionality.
