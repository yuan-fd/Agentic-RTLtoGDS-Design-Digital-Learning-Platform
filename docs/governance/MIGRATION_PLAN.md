# Architecture migration plan

This plan is deliberately ordered as small, independently reversible slices.
It is not authorization to execute every slice.  A slice begins only after the
prior one has its stated evidence and no stop condition in `AGENTS.md` applies.

## Slice ordering

| Slice | Single architectural purpose | Expected boundary change | Main risk | Acceptance / rollback |
| --- | --- | --- | --- | --- |
| 0 — Governance freeze | Make the intended platform rules explicit | None; documentation and inventory only | Mistaking policy for code completion | Review root governance docs; rollback is a normal Git revert. |
| 1 — Capability task-factory port | Stop Scheduler from constructing ORFS tasks directly | `scheduler -> concrete ORFS builder` becomes `scheduler -> injected TaskFactory contract` | Existing L1/RTL-to-ORFS callers may assume ORFS-only fields | Focused compiler/composition tests plus ORFS task parity fixture; revert the small injection/contract change. |
| 2 — Runtime-only execution path | Retire direct `Worker -> ORFSRunner` ownership | Legacy worker becomes a compatibility projection or delegates to Runtime | Queue recovery/cancellation semantics could diverge | Same task yields one Runtime run/attempt/artifact trace; retain old worker behind a feature flag until parity. |
| 3 — Evaluator boundary narrowing | Keep execution collection separate from protected evaluation | `ORFSRunner` returns raw evidence; Runtime invokes a dedicated protected evaluator after raw-artifact validation | Metric/provenance identity can change accidentally | Golden artifact parity and hash/metric comparison under frozen toolchain; rollback preserves original runner. **Accepted 2026-08-30; see `SLICE_003_PROTECTED_EVALUATOR_GATEWAY.md`.** |
| 4 — API composition extraction | Split application composition from HTTP transport and `ApiState` | API routes call small services/factories; scripts stop importing the HTTP façade | Large untested endpoint surface | Route-contract tests and selected experiment-driver migration; restore legacy façade if a route regresses. |
| 5 — Legacy algorithm quarantine | Remove local BO/GP/stateful agents from default product composition without deleting research code | Product registry admits only source-locked optimizer plugins | Historical tests may implicitly import legacy exports | Default-path test proves ORFS-Agent plugin selection; retain modules and explicit research-only import paths. |
| 6 — External-plugin admission standardization | Apply one lock/license/native-smoke/platform-smoke checklist to every integration | Per-plugin manifests gain consistent admission metadata | License or native environments may block admission | Each plugin gets Green/Yellow/Red record; unqualified plugins remain disabled, not bypassed. |
| 7 — UI/read-model cleanup | Render only Runtime/evaluator facts and admitted capability state | UI removes legacy strategy toggles and invented statuses | Product presentation regressions | Browser/read-model contract tests; return to previous read-only component if needed. |

## Rules for every slice

1. Change one boundary only.  Do not combine UI, API, Runtime, evaluator, and
   optimizer changes merely because files are nearby.
2. Do not alter a benchmark, evaluator, protocol, statistics, source lock, or
   historical artifact to satisfy acceptance.
3. Do not turn an unresolved upstream source into a local rewrite.
4. State the exact before/after dependency edge, all files, tests, smoke
   command, artifact path, and rollback before editing code.
5. If a required change crosses unrelated subsystems, stop and redesign the
   slice rather than adding compatibility layers.

## First executable slice: detailed plan

### Slice 1 — Capability task-factory port

**Intent.**  Remove the direct concrete ORFS dependency from
`packages/scheduler/.../nl_control.py` and `composition.py`.  Scheduler will
ask an injected, typed task factory for a capability-constrained `TaskSpec`.
This does not change ORFS algorithms, L1 language policy, Runtime behavior,
the evaluator, or any web route.

**In scope.**

- Add a minimal task-factory protocol and request value type to
  `packages/contracts` (no ORFS names or defaults).
- Add a Scheduler constructor dependency on that protocol.
- Implement one ORFS-specific factory at the integration/execution composition
  edge, mapping an already-validated generic request to the existing
  `build_orfs_task` without changing it.
- Update only the composition root used by the affected Scheduler tests.
- Add parity tests: the old frozen fixture and factory path produce equivalent
  TaskSpec identity/parameters for the same registered RTL and policy input.

**Explicitly out of scope.**  API route extraction, runtime migration,
optimizer replacement, design-space changes, RTLScout behavior, ORFS runner
changes, UI changes, benchmark/evaluator changes, and any deletion.

**Expected files.**  A new small contract module plus exports; the two
Scheduler helpers above; one ORFS factory near `orfs_plugin.py`; the minimal
composition root; focused tests.  If materially more files are required,
STOP and issue the problem/options report required by `AGENTS.md`.

**Acceptance evidence.**

1. Static import test proves Scheduler no longer imports
   `openroad_platform_execution` or `build_orfs_task`.
2. Unit tests prove unknown capabilities and out-of-policy parameters fail
   before Runtime submission.
3. A fixture parity test proves the ORFS factory preserves the existing
   `TaskSpec` fields for a frozen registered-design case.
4. One bounded real ORFS Runtime smoke uses the new factory; it records
   run/attempt IDs, terminal state, artifact hashes, evaluator version, and
   unchanged protected-input hashes.  It is an integration smoke, not a PPA
   improvement claim.
5. `git diff --check`, focused tests, then the full suite pass without
   weakening assertions.

**Rollback.**  Revert the slice commit.  No migration of databases, artifacts,
or external source is needed because the factory is a pure task-construction
boundary and old historical paths remain untouched until later slices.
