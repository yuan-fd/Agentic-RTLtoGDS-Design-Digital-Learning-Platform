# Slice 006: External L2 scheduler ownership

Status: completed structural migration; no experiment inputs or results changed.

## Problem

`ExternalOptimizerLoopService` is the durable state machine that schedules
baseline replicas, frozen warm-up observations, an admitted external
optimiser task, candidate execution, and confirmation.  It does not implement
GP/EI, but it previously lived at `apps/api/services/external_l2_service.py`.
That directory is reserved for HTTP/application composition.  The placement
would make the API layer the owner of campaign lifecycle and would force
future command-line workers and plugins to depend on the Web layer.

## Boundary and change

The unchanged service moved to
`packages/scheduler/src/openroad_platform_scheduler/external_l2_service.py`.
The Scheduler package exports it.  The API and both ORFS-Agent runner scripts
now import it from Scheduler.  `apps/api/services` no longer exports or owns
the service.

No transition logic, protocol field, evaluator, candidate, task parameter,
plugin adapter, source lock, toolchain, benchmark, SDC, seed, or historical
artifact was changed.

## Dependency change

```text
Before: API/service -> ExternalOptimizerLoopService -> Runtime / plugin
After:  API/composition -> Scheduler.ExternalOptimizerLoopService -> Runtime / plugin
         CLI runner ----^ 
```

The external optimiser still owns numeric GP/EI proposals.  Scheduler owns
only the generic, durable lifecycle contract.

## Verification and rollback

Focused tests passed after the move:

```text
15 passed
tests/test_external_l2_service.py
tests/test_orfs_agent_plugin.py
tests/test_package_architecture_boundaries.py
```

Python compilation of the two ORFS-Agent runners, the moved module, and
`apps/api/app.py` passed; `git diff --check` passed.  A new architecture test
rejects any future `*l2*.py` file under `apps/api/services`.

Rollback is a source-location revert only.  It has no experiment data to
delete or recompute.
