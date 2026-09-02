# Architecture audit: current state to target state

Audit date: 2026-08-30
Method: non-invasive source inspection, import-boundary test inspection,
manifest/lock inspection, and repository status inspection.  No production
logic, benchmark, evaluator, artifact, or external source was changed.

## Executive finding

The repository already contains the essential platform kernel: dependency-free
contracts, a durable Runtime with attempt/workspace control, process
supervision, a plugin registry, artifact checks, and an ORFS plugin boundary.
The primary risk is not missing
classes; it is **historical composition leakage**.  A monolithic API state
object and several Scheduler helpers still know concrete ORFS and local
optimizer details.  Continuing to add features there would recreate the
"platform implements every algorithm" failure mode.

## Current module map

```text
apps/api/app.py (about 4,005-line mixed application façade at the P0 baseline)
  |-- contracts: DesignGoal, TaskSpec, learning/RTL/L1 types
  |-- analysis: evaluator, local BO/GP/state tuning, EDAIR, reports
  |-- execution: ORFS/RTL/3D/plugin manifest and task builders
  |-- scheduler: Runtime, campaigns, L1, state/checkpoint stores
  `-- API services: auth, design, and read model

packages/contracts
  `-- pure versioned public types
packages/analysis
  `-- deterministic evaluator/data views + historical local algorithms
packages/execution
  `-- adapters, process control, registry, ORFS/RTL/3D integrations
packages/scheduler
  `-- durable Runtime, queues/campaigns + legacy concrete task construction
packages/visualization
  `-- non-authoritative layout/schematic views
integrations
  `-- source locks, manifests, license audits, thin adapter entrypoints
```

## Observed package dependency graph

Source inspection identifies this intended package direction:

```text
contracts  <- analysis  <- execution  <- scheduler  <- apps/api
    ^             ^             ^              ^
    |             |             |              `-- scripts/tests import ApiState
    `-------------+-------------+----------------- visualization (contracts only)
```

There is no confirmed package-level import cycle today.  The graph nevertheless
has architectural coupling hotspots:

1. `apps/api/app.py` imports all lower layers and embeds multiple historical
   policies, making API transport the practical owner of workflow behavior.
2. `scheduler/nl_control.py` and `scheduler/composition.py` import
   `openroad_platform_execution.build_orfs_task`; Scheduler thus knows a
   specific plugin instead of a capability contract.
3. `scheduler/worker.py` directly constructs `ORFSRunner`, retaining a second
   legacy execution route beside `WorkflowRuntime`.
4. `execution/orfs_runner.py` still imports analysis pipeline/report/evidence
   code.  Its evaluator/report ownership needs a later dedicated audit; P0
   makes no claim that this boundary has already been migrated.
5. A large group of experiment scripts imports `apps.api.app.ApiState`.  This
   makes a product HTTP façade an unofficial research composition library.

## Platform core versus algorithm intrusion

| Category | Current evidence | Audit conclusion |
| --- | --- | --- |
| Platform core | contracts, Runtime/RuntimeStore, ProcessAdapter/Guardian, registry, toolchain policy, artifact validation, deterministic evaluator/statistics | Keep and protect. |
| Proper thin external integration | pinned manifest, bounded adapter process and `PluginResult` | Required pattern for future external intake; P0 does not assert an uncommitted integration is admitted. |
| Research algorithm intrusion | local BO/GP, iterative-agent, offline-policy and evolve-agent modules in `packages/analysis` | Freeze as legacy research code; do not make them the default product algorithm. |
| Concrete-plugin knowledge in platform policy | Scheduler imports `build_orfs_task`; worker imports `ORFSRunner` | Future migration: introduce a typed capability port instead of a concrete builder. |
| Unadmitted source | StateTune and AgenticPD have unresolved license status in existing locks | Do not execute or distribute as plugins. |

## Reuse and thin-adapter decisions

| Asset | Decision | Why |
| --- | --- | --- |
| ProcessGuardian, ProcessAdapter, RuntimeStore, PluginRegistry | Reuse as kernel | They implement the platform's distinct responsibilities: bounded execution and trustworthy state. |
| ORFS runner / plugin | Reuse, then narrow its evaluator coupling | It is the actual backend needed for fair L2 measurement; no optimizer belongs in it. |
| RTLScout and a future admitted L2 optimizer | Thin adapter only | Their pinned upstream algorithms should remain upstream-owned. |
| StateTune | Source-audit only | Missing license blocks executable admission. |
| Local optimizer and agent modules | Preserve but retire from default paths | They are historical implementation experiments, not the target plugin architecture. |
| EDAIR/evaluator parsers and statistics | Reuse as protected platform infrastructure | They make raw EDA artifacts searchable/AI-addressable without allowing the optimizer to redefine QoR. |

## Target architecture

The target is the ownership model declared by
`P0_PRODUCT_BOUNDARY_FREEZE.md`: typed L1 requests are admitted by Scheduler;
Runtime executes an immutable `TaskSpec`; adapters translate only to pinned
upstream plugins; a protected evaluator emits canonical QoR from raw artifacts.
The dependency change that matters most is:

```text
before: Scheduler -> execution.build_orfs_task -> concrete ORFS task
after:  Scheduler -> future typed capability contract -> selected plugin
```

This makes L1, RTL, DSE, repair, ECO, source optimization, and EDAIR siblings
under one contract instead of special cases embedded in Scheduler or API.

## Protected-component check

This audit did not modify benchmark content, RTL, PDK/toolchains, SDC/timing
targets, QoR evaluator behavior, experiment protocol, statistics, artifacts,
or source locks.  Existing artifacts are intentionally not used as evidence of
new performance in this document.
