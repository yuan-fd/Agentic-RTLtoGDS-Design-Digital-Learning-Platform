# Slice 001: capability task-factory boundary

Status: accepted at the slice boundary and verified on 2026-08-30.

## Intent and boundary

This slice removes the Scheduler's direct imports of the concrete ORFS task
builder and ORFS parameter validator.  Scheduler now asks a generic
`RTLToGDSFactory` for a bounded `TaskSpec`; the ORFS implementation lives in
the execution/integration layer.  This is a dependency-boundary change only.

It does not replace ORFS, alter an optimizer, redesign L1 language policy,
move API routes, change Runtime lifecycle, modify evaluator logic, change a
benchmark, or delete legacy code.

## Changed ownership

```text
Before
  Scheduler -> build_orfs_task / validate_orfs_parameters -> ORFS

After
  Scheduler -> RTLToGDSFactory contract -> ORFSRTLToGDSFactory -> existing ORFS builder
```

The factory is deliberately thin.  It validates a generic capability request,
rejects unknown request options, delegates construction to the pre-existing
`build_orfs_task`, and owns ORFS-specific parameter reconfiguration.  It does
not contain a new EDA algorithm, scheduler, QoR calculation, or shell call.

## Files in this slice

| File | Change |
| --- | --- |
| `packages/contracts/.../task_factory.py` | New dependency-free request/factory contract. |
| `packages/contracts/.../__init__.py` | Exposes the public contract. |
| `packages/execution/.../orfs_task_factory.py` | Thin ORFS mapping to the existing builder and existing allowlist validator. |
| `packages/execution/.../__init__.py` | Exposes the ORFS factory at the execution composition boundary. |
| `packages/scheduler/.../nl_control.py` | Receives a factory instead of importing the ORFS builder. |
| `packages/scheduler/.../composition.py` | Receives a factory for verified RTL and RTLScout-to-backend handoff. |
| `packages/scheduler/.../l1_orfs_service.py` | Delegates task validation/reconfiguration to the injected factory and checks capability identity. |
| `apps/api/app.py`, `scripts/run_p2_acceptance.py`, `scripts/run_p4_acceptance.py` | Explicit composition roots select `ORFSRTLToGDSFactory`. |
| focused tests | Contract parity, reject paths, L1 capability matching, integration composition, and static boundary evidence. |

## Acceptance evidence

### Static and focused tests

The focused suite passed with 30 tests:

```text
tests/test_task_factory_boundary.py
tests/test_nl_react.py
tests/test_l1_orfs_service.py
tests/test_rtlscout_plugin.py
tests/test_package_architecture_boundaries.py
tests/test_common_evaluator.py
```

The slice-specific AST check verifies that `nl_control.py`, `composition.py`,
and `l1_orfs_service.py` no longer import `openroad_platform_execution`.
Existing Runtime/Worker/white-box execution dependencies remain explicitly out
of scope and are not hidden by a broad new lint rule.

### Real bounded ORFS smoke

Command:

```text
python3 scripts/run_p2_acceptance.py \
  --output-root var/slice1-factory-smoke-20260830-evaluator \
  --timeout 7200 --stage-timeout 3600
```

Frozen input: `tests/fixtures/p2_mux_2to1.v`; platform: `nangate45`; target:
`finish`; seed: `1`; task construction: `ORFSRTLToGDSFactory`.

Recorded evidence:

- Runtime run: `61dbf2609be6412cbd74dcc45887a296`, terminal `succeeded`.
- 34 validated Runtime artifacts, including final GDS, DEF, netlist, ODB,
  configuration, toolchain snapshot, parameter contract, and raw reports.
- `implementation_valid=true`, `gds_complete=true`; runtime 77.743 seconds.
- Protected evaluator output:
  `var/slice1-factory-smoke-20260830-evaluator/common_evaluator_v3.json`.
  Evaluator schema `3`, id
  `a86a42682d56af38ff50c76dd455fda5a047092d147debd4a0bcaf00fdd66c39`,
  feasibility gate passed with no missing artifacts/metrics or violation.
- Shared ORFS/OpenROAD toolchain snapshot was unchanged before and after the
  run, as recorded in `acceptance_summary.json`.

This evidence establishes integration and evaluator continuity only.  It does
not claim RTL functional verification (`functionally_verified=false`) or any
PPA improvement.

### Repository-wide regression note

The repository has a large, dirty historical worktree and a long-running full
suite that exercises unrelated TaiWei, EDACraft, web, legacy-learning, and
external-source paths.  Slice 001 does not claim ownership of those paths.
The focused static, unit, integration, real-ORFS, and evaluator checks above
are the acceptance evidence for this one boundary.  A clean-worktree full-suite
gate remains a release-level requirement and must be recorded separately rather
than "fixed" by changing unrelated tests in this slice.

## Protected components and rollback

No benchmark, RTL, PDK, SDC/timing target, toolchain source, evaluator logic,
statistics definition, external-source lock, or historical artifact was
modified.  The real run used a fresh workspace and an independent SQLite
runtime database under `var/`.

Rollback is a revert of the slice files above.  It requires no database data
migration and does not remove either smoke evidence directory.  Historical
direct-builder paths outside these three Scheduler task-construction routes are
unchanged and remain covered by future slices.
