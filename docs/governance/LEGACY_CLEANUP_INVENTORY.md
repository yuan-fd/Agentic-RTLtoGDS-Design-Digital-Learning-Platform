# Historical logic and cleanup inventory

Audit date: 2026-08-30.  Classification is an operational instruction, not a
claim that an item is useless.  Nothing in this inventory is deleted, moved,
or rewritten by this governance phase.

## Classification meaning

- **ACTIVE** — part of the supported platform kernel or an admitted thin
  integration path.
- **LEGACY** — existing code/data retained for compatibility, investigation,
  or staged migration; do not extend it for new product work.
- **INVALID** — not eligible for execution or product claims under current
  license/protocol/security rules.
- **HISTORICAL_EVIDENCE** — records needed to explain prior results; preserve
  unchanged and do not treat as current capability.
- **UNKNOWN** — ownership or execution status has not yet been proven.

## Inventory

| Location / scope | Class | Evidence and rationale | Action now |
| --- | --- | --- | --- |
| `packages/contracts/src/openroad_platform_contracts/` | ACTIVE | Public `TaskSpec`, `PluginManifest`, `PluginResult`, semantic L1, RTL, and learning types have no reverse imports. | Preserve as the contract root; add no plugin-specific policy. |
| `packages/execution/.../adapter.py`, `process_guardian.py`, `registry.py`, `toolchain.py` | ACTIVE | Runtime process boundary, cancellation/timeout, manifest registry, and bounded environment are platform-kernel responsibilities. | Reuse; protect from optimizer-specific changes. |
| `packages/scheduler/.../runtime.py`, `runtime_store.py` | ACTIVE | Runtime owns attempts, leases, events, and durable run state. | Preserve as the only run-state authority. |
| Evaluation/evidence extensions not present in the committed tree | UNKNOWN | P0 cannot treat future evaluator or evidence modules as current platform facts. | Admit only through a later evidence-backed slice. |
| Future ORFS-Agent integration and adapter | UNKNOWN | P0 selects this intended upstream L2 direction but does not claim an uncommitted source lock or adapter is executable. | Pass the external-project intake gate before registration or execution. |
| `packages/execution/.../orfs_runner.py`, `orfs_plugin.py` | ACTIVE | Real ORFS execution is needed; its evaluator/report boundary still requires audit. | Retain; later separate optional reporting/evidence production from low-level execution without changing protected components. |
| `packages/analysis/.../optimization.py`, `iterative_agent.py`, `evolve_agent.py`, `offline_policy.py` | LEGACY | They contain local BO/GP, agent, or policy algorithms.  The governance target is a future admitted external optimizer, not further platform-layer algorithm growth. | Freeze for explicit, preregistered comparison/reproduction only; do not expose through product registry, API, Web or L1. |
| `docs/self_evolution_report.md`, `docs/P17_EDACRAFT_WEB.md` and prior phase acceptance reports | HISTORICAL_EVIDENCE | They record earlier BO/GP, self-evolution, or extension exploration and can contain superseded product wording. | Preserve unchanged for provenance; they are not canonical product authority and must not reopen a default product route. |
| `packages/analysis/.../closed_loop.py`, `hypothesis_ledger.py` | LEGACY | Useful data-only primitives are mixed with historical L2 controller semantics; each exported API requires individual evaluation. | Retain evidence utilities; decide each exported API only during the DSE-boundary slice. |
| `packages/scheduler/.../nl_control.py`, `composition.py` | LEGACY | They import and call concrete `build_orfs_task`, so Scheduler knows ORFS implementation details: a boundary violation. | First migration candidate: replace direct concrete construction with an injected capability task factory. |
| `packages/scheduler/.../worker.py` | LEGACY | Direct `ORFSRunner` construction preserves an older execution path alongside `WorkflowRuntime`: a boundary violation. | Do not extend; migrate/retire only after a Runtime-only acceptance run. |
| `packages/scheduler/.../patch_registry.py` and execution white-box/coding files | LEGACY | Scheduler imports execution patch types; white-box work is outside current L1-L2 focus. | Quarantine from default product workflow, API and Web; preserve source and evidence for future L3/L4 contract work. |
| `apps/api/app.py` | LEGACY | About 4,005 lines at the P0 baseline import contracts, analysis, execution, scheduler, RTL, 3D, and application services: a monolith. | Freeze feature growth; extract through small slices, beginning with task construction boundaries—not a wholesale rewrite. |
| Scripts importing `apps.api.app.ApiState` | LEGACY | Many campaign and audit scripts use the API state as a laboratory façade. | Preserve for provenance; new research runners should use a dedicated composition fixture after API extraction. |
| Future StateTune intake | UNKNOWN | No StateTune source/lock is part of the P0 baseline tree. | If introduced, apply the external-project intake gate before any execution claim. |
| `integrations/agenticpd/` | INVALID | Inventory reports no license declaration. | Internal source audit only; no product/plugin admission until resolved. |
| `integrations/taiwei_pin_3d/` | UNKNOWN | TaiWei has a pinned 3D toolchain and its own capability contract; it is not a 2D dependency. | Keep it independently scoped from L1/L2 product state; reclassify only after its individual admission evidence is reviewed. |
| `integrations/rtlscout/` | ACTIVE | RTLScout is the sole product RTL-creation backend after SpecIR and independent verification. | Keep its pinned adapter boundary; no direct-LLM or second product RTL generator. |
| `integrations/dplevolve/`, `edacraft*` | UNKNOWN | Locks and license notes exist, but capability maturity and native toolchain readiness differ. | Keep outside the product path; admit each only after its own native + platform smoke. |
| `artifacts/`, `runs/`, `experiments/`, `studies/`, `memory_snapshots/`, `plan/`, `project_kb/`, `knowledge/` | HISTORICAL_EVIDENCE | They contain prior experiments, plans, and memory; a current manifest may later prove a different classification, but age or duplicate-looking names alone do not remove provenance value. | Do not delete.  Future inventory must record owner, hash, external citation, and retention policy. |
| `deliverables/`, `demos/`, `workflows/`, unclassified scripts | UNKNOWN | Status, caller, and evidence value were not exhaustively proven in this non-invasive phase. | Require a caller/provenance check before reclassifying or deleting. |

## Cleanup gate

An item can move from `LEGACY` or `UNKNOWN` to deletion only after a review
records all of: active-path non-use, no experiment/publication provenance,
no external reference, Git recoverability, exact deletion target, and rationale.
Otherwise the safe operation is an archive/quarantine marker, not deletion.
