# Historical logic and cleanup inventory

## Teaching rebaseline (2026-09-20)

The table below is the current product classification for the teaching
rebuild. It is authoritative for navigation and new work; the older inventory
that follows is retained as audit history and is not a second product roadmap.

| Scope | Classification | Decision |
| --- | --- | --- |
| `packages/contracts/.../teaching_catalog.py`, `evidence_exchange.py` | ACTIVE | Stable teaching contracts; no execution or database access. |
| M1 RTL-to-GDS app | TEACHING_MODULE | Active independent entrypoint; Direct LLM → verification → ORFS → GDS. |
| Teaching Hub, M2, M3 and M4 | TEACHING_MODULE | Registered future modules; no active implementation entrypoint yet. |
| M1 Course Lab | TEACHING_MODULE | First vertical slice: Direct LLM → verification → ORFS → GDS. |
| M2 Direct LLM vs RTLScout | TEACHING_MODULE | Independent generator comparison after M1. |
| M3 baseline vs ORFS-Agent | TEACHING_MODULE | Protocol-faithful backend comparison after M1. |
| M4 Flow / Recipe Scripting Lab | TEACHING_MODULE | Allowlisted, confirmed patches only. |
| Course Lab ten-exercise catalog | TEACHING_MODULE | Frozen specs, oracles, reference RTL and smoke records. |
| GCD/AES/Ibex/RISC-V/JPEG/SPI/I2C/UART/Ethernet/TinyRocket/CVA6 | SHOWCASE | Fixed RTL demonstrations, separate from Course Lab. |
| `openroad-platform-v2` HTTP boundary | ACTIVE | Only execution, identity, artifact and provenance authority. |
| Existing research/optimization and 3D entry points | HISTORICAL_EVIDENCE | Removed from active main after consumer audit; recoverable from `archive/pre-teaching-platform`. |
| Prior acceptance reports, campaign outputs and raw run records | HISTORICAL_EVIDENCE | Preserve for provenance; never claim as current module capability. |
| Unclassified scripts, demos and assets | HISTORICAL_EVIDENCE | Retained only where they document prior work; not active product entrypoints. |

The M1 delivery checkpoint completed the deletion gate for old active code:
active consumers were test and entrypoint consumers only, the pre-teaching
commit is recoverable as `archive/pre-teaching-platform`, and the removed paths
are not started by any active launcher. The historical rows below describe the
pre-cleanup tree and are retained for provenance, not as runtime instructions.

Audit date: 2026-09-20. Classification is an operational instruction, not a
claim that historical material is useless.

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
| `orfs-agent/upstream_full_policy`, `ORFSAgentFullDomain`, and the clean detached `730f1fa1` source | ACTIVE | The typed contract preserves the exact upstream 12-D constraint set, ECP/DWL/COMBO, variable clock, and upstream scikit-optimize GP/EI. Internal execution authorization, source identity, license, environment, and Runtime smoke evidence are recorded. | Use as the sole L2 optimizer policy. Keep candidate execution and protected evaluation under Runtime authority. |
| `ORFSAgentDomain`, `materialize_dataset`, and `native_agent` fixed-timing eight-field profile | LEGACY | This was the former shared-domain fair-comparison bridge. It cannot express the full upstream domain and can be incompatible with upstream PDK clock constraints. | Preserve for decoding historical evidence. Do not expose as complete ORFS-Agent, extend it, snap proposals, or use it as the product L2 route. |
| `apps/api/app.py` external-optimizer create/advance methods, `ExternalOptimizerLoopService`, `scripts/run_dse_controller_worker.py`, and the old Web L2 controls | LEGACY | They operate the historical `external-orfs-agent-loop-v1` reduced-domain/fixed-clock protocol. Slice 024 closes both public and in-process mutation entry points while retaining checkpoint reads and source evidence. | Keep create/advance fail closed. Preserve scheduler tests and old checkpoints for provenance; do not resume, repair, or relabel this as complete ORFS-Agent. |
| `docs/governance/ORFS_AGENT_PAPER_COMPARABLE_PROTOCOL.md`, `scripts/run_orfs_agent_paper_campaign.py`, `scripts/run_orfs_agent_target_feasibility_preflight.py`, and v3–v8b ORFS-Agent campaign directories | HISTORICAL_EVIDENCE | These runs implement the former fixed-SDC, five-knob, final-signoff-gated comparison protocol. The product decision on 2026-09-02 makes that protocol non-default for ORFS-Agent; its raw artifacts remain essential to explain prior failures and adapter fixes. | Preserve unchanged; do not extend, relabel as complete ORFS-Agent reproduction, or delete. A later migration may retain it as an explicitly selected scientific control only. |
| Full ORFS-Agent paper-flow candidate execution at ORFS `ce8d36a7` | UNKNOWN | Internal execution is authorized, but isolated matching OpenROAD/Yosys build, submodule/tool audit, native candidate smoke, and Runtime candidate smoke are not yet complete. This is distinct from the now-active policy adapter. | Continue the intake gate. Do not claim end-to-end reproduction or use the older `51ad1231` toolchain as paper-identical evidence. |
| `packages/execution/.../orfs_runner.py`, `orfs_plugin.py` | ACTIVE | Real ORFS execution is needed; its evaluator/report boundary still requires audit. | Retain; later separate optional reporting/evidence production from low-level execution without changing protected components. |
| `packages/analysis/.../optimization.py`, `iterative_agent.py`, `evolve_agent.py`, `offline_policy.py` | LEGACY | They contain local BO/GP, agent, or policy algorithms.  The governance target is a future admitted external optimizer, not further platform-layer algorithm growth. | Freeze for explicit, preregistered comparison/reproduction only; do not expose through product registry, API, Web or L1. |
| `docs/self_evolution_report.md`, `docs/P17_EDACRAFT_WEB.md` and prior phase acceptance reports | HISTORICAL_EVIDENCE | They record earlier BO/GP, self-evolution, or extension exploration and can contain superseded product wording. | Preserve unchanged for provenance; they are not canonical product authority and must not reopen a default product route. |
| `packages/analysis/.../closed_loop.py`, `hypothesis_ledger.py` | LEGACY | Useful data-only primitives are mixed with historical L2 controller semantics; each exported API requires individual evaluation. | Retain evidence utilities; decide each exported API only during the DSE-boundary slice. |
| `packages/scheduler/.../nl_control.py`, `composition.py` | LEGACY | They import and call concrete `build_orfs_task`, so Scheduler knows ORFS implementation details: a boundary violation. | First migration candidate: replace direct concrete construction with an injected capability task factory. |
| `packages/scheduler/.../worker.py` | LEGACY | Direct `ORFSRunner` construction preserves an older execution path alongside `WorkflowRuntime`: a boundary violation. | Do not extend; migrate/retire only after a Runtime-only acceptance run. |
| `packages/scheduler/.../patch_registry.py` and execution white-box/coding files | LEGACY | Scheduler imports execution patch types; white-box work is outside current L1-L2 focus. | Quarantine from default product workflow, API and Web; preserve source and evidence for future L3/L4 contract work. |
| `apps/api/app.py` | LEGACY | About 4,005 lines at the P0 baseline import contracts, analysis, execution, scheduler, RTL, 3D, and application services: a monolith. | Freeze feature growth; extract through small slices, beginning with task construction boundaries—not a wholesale rewrite. |
| `apps/l1_trace_dashboard/` | LEGACY | S7 produced a standalone read-only, completed-trace teaching viewer. It has no session, natural-language submission, clarification workflow, Runtime command path, live event stream, campaign boundary, or recovery authority; treating it as the L1 product front door would turn the Workbench into a static playback UI. | Preserve unchanged as `TRACE_VIEWER_PROTOTYPE` and bounded evidence viewer. Do not extend it for the L1 product. The new `apps/l1_workbench/` must be a separate application, admitted only after the durable L1 session/event boundary exists. |
| Scripts importing `apps.api.app.ApiState` | LEGACY | Many campaign and audit scripts use the API state as a laboratory façade. | Preserve for provenance; new research runners should use a dedicated composition fixture after API extraction. |
| Future StateTune intake | UNKNOWN | No StateTune source/lock is part of the P0 baseline tree. | If introduced, apply the external-project intake gate before any execution claim. |
| `integrations/agenticpd/` | INVALID | Inventory reports no license declaration. | Internal source audit only; no product/plugin admission until resolved. |
| `integrations/taiwei_pin_3d/` | UNKNOWN | TaiWei has a pinned 3D toolchain and its own capability contract; it is not a 2D dependency. | Keep it independently scoped from L1/L2 product state; reclassify only after its individual admission evidence is reviewed. |
| `integrations/rtlscout/` | ACTIVE | RTLScout is the sole product RTL-creation backend after SpecIR and independent verification. | Keep its pinned adapter boundary; no direct-LLM or second product RTL generator. |
| `integrations/orassistant/` and the pinned detached ORAssistant/OpenROAD corpus checkouts | ACTIVE | Read-only `knowledge.openroad.retrieve` uses upstream native preprocessing/BM25 and Runtime-registered citation artifacts. MCP, database, network, unsafe FAISS loading and EDA execution are denied. | Use only as a cited knowledge service; never treat retrieved prose as measured QoR or Runtime state. |
| `rtlscout_adapter._codex_cli_candidates` local candidate loop | LEGACY | It let Codex author RTL and called upstream `run_eval.py`, but did not invoke `run_benchmark.py/core.agent.RTLAgent`; it cannot support a native-RTLScout claim. | Preserve for historical regression/evidence only. The active Codex path must use the provider-only native driver. |
| `integrations/dplevolve/`, `edacraft*` | UNKNOWN | Locks and license notes exist, but capability maturity and native toolchain readiness differ. | Keep outside the product path; admit each only after its own native + platform smoke. |
| `artifacts/`, `runs/`, `experiments/`, `studies/`, `memory_snapshots/`, `plan/`, `project_kb/`, `knowledge/` | HISTORICAL_EVIDENCE | They contain prior experiments, plans, and memory; a current manifest may later prove a different classification, but age or duplicate-looking names alone do not remove provenance value. | Do not delete.  Future inventory must record owner, hash, external citation, and retention policy. |
| `deliverables/`, `demos/`, `workflows/`, unclassified scripts | UNKNOWN | Status, caller, and evidence value were not exhaustively proven in this non-invasive phase. | Require a caller/provenance check before reclassifying or deleting. |

## Cleanup gate

An item can move from `LEGACY` or `UNKNOWN` to deletion only after a review
records all of: active-path non-use, no experiment/publication provenance,
no external reference, Git recoverability, exact deletion target, and rationale.
Otherwise the safe operation is an archive/quarantine marker, not deletion.

## A2-ORFO admission attempts (2026-09-05)

| Path | Classification | Reason |
| --- | --- | --- |
| `var/evidence/a2-orfo-single-feedback-20260905-r1` | `HISTORICAL_EVIDENCE` | Fail-closed structured-output schema incompatibility; no EDA candidate submitted. |
| `var/evidence/a2-orfo-single-feedback-20260905-r2` | `INVALID` | MODEL stage was mis-dispatched to selection; useful debugging evidence but not acceptance evidence. |
| `var/evidence/a2-orfo-single-feedback-20260905-r3` | `HISTORICAL_EVIDENCE` | Exposed upstream hard-coded/formal-domain divergence; candidate rejected before EDA. |
| `var/evidence/a2-orfo-single-feedback-20260905-r4` | `ACTIVE` | Canonical bounded A2 policy→Runtime ORFS→protected evaluation→feedback evidence. |

## RTLScout native restoration attempts (2026-09-05)

| Path | Classification | Reason |
| --- | --- | --- |
| `var/evidence/rtlscout-native-spec-to-gds-20260905-r1` | `HISTORICAL_EVIDENCE` | Driver could not import the execution package; no model or EDA ran. |
| `var/evidence/rtlscout-native-spec-to-gds-20260905-r2` | `HISTORICAL_EVIDENCE` | Isolated child lacked the contracts import root; no model or EDA ran. |
| `var/evidence/rtlscout-native-spec-to-gds-20260905-r3` | `HISTORICAL_EVIDENCE` | Ambiguous provider schema repeatedly selected `edit_file`; native feedback rejected it. |
| `var/evidence/rtlscout-native-spec-to-gds-20260905-r4` | `HISTORICAL_EVIDENCE` | Tool descriptions were present but schema branch bias remained; no passing candidate. |
| `var/evidence/rtlscout-native-spec-to-gds-20260905-r5` | `HISTORICAL_EVIDENCE` | RTL passed 65,536 vectors, but incompatible `yosys_cells` parsing correctly blocked best-design admission. |
| `var/evidence/rtlscout-native-spec-to-gds-20260905-r6` | `HISTORICAL_EVIDENCE` | Full chain and GDS succeeded; the acceptance script looked up two registered facts under incorrect keys. |
| `var/evidence/rtlscout-native-spec-to-gds-20260905-r7` | `HISTORICAL_EVIDENCE` | Accepted full chain before alternate-filename candidate archival was covered. |
| `var/evidence/rtlscout-native-spec-to-gds-20260905-r8` | `ACTIVE` | Canonical SpecIR→native RTLScout→verification/mutation→L1 promotion→ORFS/GDS/protected-evaluator evidence. |

## ORAssistant admission attempts (2026-09-05)

| Path | Classification | Reason |
| --- | --- | --- |
| `var/evidence/orassistant-native-retrieval-20260905-r1` | `ACTIVE` | Native `process_md`→`BM25RetrieverChain`→`format_docs` retrieved pinned DRT-0349 evidence with citations before platform admission. |
| `var/evidence/orassistant-platform-20260905-r1` | `HISTORICAL_EVIDENCE` | The manifest resolved a venv launcher symlink to its base interpreter, so no retrieval ran; retained as the path-identity failure. |
| `var/evidence/orassistant-platform-20260905-r2` | `HISTORICAL_EVIDENCE` | Passing programmatic-manifest Runtime smoke; superseded only as canonical evidence by the static-registry run. |
| `var/evidence/orassistant-platform-20260905-r3` | `ACTIVE` | Canonical static-manifest Runtime retrieval with four registered citation/provenance artifacts and all admission checks passing. |
