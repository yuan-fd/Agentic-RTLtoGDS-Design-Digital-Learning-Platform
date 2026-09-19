# Teaching migration progress

## Rebaseline for the independent teaching platform (2026-09-19)

The product authority is now `docs/TEACHING_PLATFORM_SPEC.md`. Slice 0 added
the teaching catalog, PDK capability/evidence contracts, and the HTTP-boundary
ADR. The first Slice 1 increment added `apps/m1_rtl_to_gds/` as an independent
M1 state module. It persists only spec/RTL-version metadata in its own SQLite
store and reaches v2 through `V2Client`; it does not import v2 code or open a
v2 database.

Focused evidence:

- `16 passed` across teaching contracts, M1 state transitions and v2 HTTP
  client contract tests;
- offline `m1_rtl_to_gds smoke: ok` (state/submission gate only, not a GDS
  acceptance);
- clocked specs without an explicit period remain `needs_clarification`;
- user edits create a new RTL version and invalidate the previous verification
  binding; unverified RTL cannot produce an ORFS submission request;
- ORFS requests use v2 schema version 3, explicit selected PDK, staged input,
  and required GDS/DEF/ODB/netlist/report artifacts.
- `integrations/rtl_verify/` is a first-party v2 Toolkit candidate. Its
  manifest validates against the v2 protocol; its adapter runs only fixed
  Verilator/Yosys compile/lint checks and preserves a failure log as partial
  evidence. It is deliberately not admitted until operator review and native
  toolchain smoke.

The real v2 verification Toolkit admission and Nangate45 end-to-end evidence
remain open gates. They cannot be represented by the offline smoke.

Latest regression: `883 passed, 1 deselected, 2 failed`. The two failures are
pre-existing environment/baseline failures: the paper ORFS checkout is dirty
including submodule state, and the historical frontend clarity test still
expects `v=20260828d` while the committed page uses `v=20260913b`. No focused
teaching test failed.

Updated: 2026-09-11

## Completed slices

- Baseline snapshot: branch `feat/llm-teaching-platform`, rollback commit
  `a27245a`, source archive under `../openroad-platform-backups/`.
- Environment doctor and launcher: commit `668dcdf`; checks the server Python
  modules, RTL tools, OpenROAD/Yosys and ORFS Makefile without installing or
  mutating shared environments.
- Compact Runtime dashboard projection: commit `b7b725d`; `GET
  /api/teaching/dashboard` reports runs, counts, authority and polling advice.
- Web run listing now consumes the compact dashboard projection while retaining
  the existing Runtime detail/artifact endpoints.
- Experiment identity (`experiment_id`), teaching mode and agent phase are
  projected from existing TaskSpec labels; no parallel database was added.
- Bounded teaching mode contract and catalog: `guided`, `open`, `challenge`;
  exposed at `GET /api/teaching/modes`.
- L1 session creation accepts the bounded `teaching_mode` value and carries it
  into Runtime TaskSpec labels for Dashboard projection; default is `guided`.
- Mode-specific request validation rejects custom Guided fields and requires
  objective plus hypothesis for Challenge; accepted context is carried as
  TaskSpec labels. Open Lab may record a hypothesis for free exploration.
- Guided/Open/Challenge validation is covered by focused contract tests; the
  existing L1 API remains backward compatible because omitted mode defaults to
  Guided.
- Backend workspace exposes the three learning modes and submits them through
  the real L1 Runtime session route; Open has an objective field and Challenge
  adds a hypothesis field.
- The managed launcher now starts four Runtime worker slots by default
  (`WORKER_COUNT`, bounded to 1–16); each slot has its own heartbeat/lock while
  Runtime lease claiming remains the concurrency authority.
- Teaching metadata is durable in the existing L1 session store, survives
  Workbench restart, and reaches baseline and candidate Runtime tasks.
- Web submission creates and executes a real L1 Runtime experiment, then
  refreshes the Runtime-backed run list.
- The browser path uses the main API's existing `/api/craft/plans` execution
  route; the standalone L1 server remains an internal vertical-slice harness.
- Open Lab can copy a Runtime run into an independent task and apply bounded
  `place_density`, `core_utilization_pct`, or `minimum_die_size_um` overrides;
  source runs remain immutable and provenance is recorded.
- Direct LLM RTL output can be registered as `direct-llm-v1` against a frozen
  verification package, then submitted through the shared RTL verification
  route; RTLScout and Direct LLM candidates have a common comparison read
  model with measured QoR metadata and a selectable trend metric.
- Direct LLM registration is intentionally separate from verification: a
  candidate remains `not_evaluated` until the shared Runtime lint/simulation/
  formal gates record evidence.
- Native BO/GP campaign creation is exposed at `/api/v2/closed-loops`; A2
  campaign status/list operations remain bound to the L1 Workbench session.
- Rule Batch submits 1–6 independent Runtime candidates with a shared batch
  identifier and the Dashboard projects aggregate progress for that batch.

## Evidence

- `python3 -m pytest -q`: `841 passed, 1 deselected` on the inherited primary
  environment.
- `python3 scripts/run_v2_frontend_suite.py --output /tmp/teaching-frontend-suite-20260911 --repeats 1`:
  compile, simulation and lint all passed for the fixed v2 RTL suite.
- Focused dashboard/doctor/web tests: `19 passed` across the executed test
  selections.
- `node --check apps/web/assets/app.js` and Python compile checks passed.
- Frontend binding and comparison checks: `11 passed` across the web clarity,
  RTL comparison, and teaching dashboard selections.

## Current next slice

Next: validate the connected route in a browser and with a bounded smoke, then
connect Rule Batch and A2 campaign actions to the teaching UI without
weakening their native protocols.

## BO teaching route correction

Problem: commit `263fc78` used a no-op wrapper and dynamic method-name lookup
to evade a historical source-string assertion. That did not establish a
product boundary. Evidence: the wrapper forwarded the payload unchanged.
Option A was to retain the wrapper; Option B removes it and updates the
historical assertion to the approved teaching authority. Recommendation and
implementation: B. The HTTP handler again calls the native service directly;
verified-lineage and protocol validation stay in that service. The P0 snapshot
is retained and labelled historical. Rollback: revert the correction commit.

- Main Web now exposes the configured Workbench through owner-scoped teaching
  session routes and the backend page provides Start L1, execute, authorize A2,
  and schedule-next controls. A2 remains session/Goal bound; no state is copied
  into the main Runtime database. Commit `643b3e1`.
- Added owner-scoped `GET /api/teaching/sessions/<id>/learning`, projecting an
  evidence-gated `eligible_for_review` state from observed Runtime status,
  successful terminal status, and evidence pointers. It never promotes data
  automatically or writes public knowledge.

- A2 durable-controller replay acceptance fixed the native initializer capability registration and completed with `accepted: true`; evidence is under `docs/evidence/a2-controller-acceptance-20260912/` (SHA-256 `f857152247c6fa68572d8f46a2dd039dfd38c8f465b0f8bc477bb55e2ef2471a`). This validates protocol/controller invariants, not a new EDA campaign.

- The first fresh A2 single-feedback bounded acceptance (`real-r4`) reached the
  real ORFS observation stage but failed in the platform-managed Codex policy
  provider because the selected model was at capacity. This is recorded in
  `var/evidence/a2-orfo-single-feedback-20260912-real-r4/runtime.sqlite` and
  is not counted as a successful A2 campaign. The valid historical checkpoint
  for a retry is the r3 handoff state (`pipeline-ef2fd9f80e8940a1b796a68de5af9916`),
  which contains 75 measured observations; the r2 checkpoint contains none and
  must not be used as the historical dataset.

- A later retry (`real-r13`) used the r3 checkpoint and reached the native
  `SELECTION` policy stage after the provider retry change, then failed on a
  subsequent long Codex request with the same capacity response. It remains a
  partial real run, not a completed A2 acceptance; its Runtime database is
  preserved under `var/evidence/a2-orfo-single-feedback-20260912-real-r13/`.

## Ibex teaching baseline

- The lesson baseline action now submits a server-pinned `sky130hd/ibex`
  reference through `/api/teaching/reference-baseline`, carrying the complete
  RTL bundle, fixed SDC, source fingerprint, and ORFS commit.
- A real Runtime run completed successfully with finish artifacts and parsed
  evidence (area 155774, setup WNS -0.0469225, DRC errors 0). The evidence is
  recorded in `docs/evidence/IBEX_TEACHING_RUNTIME_BASELINE_20260912.md`.
- The baseline proves the Runtime path and evidence collection. The browser
  dashboard still needs a connected run against the live web service, and the
  second parameter-comparison run remains outstanding.

- The second controlled Runtime run completed with only placement density
  changed from 0.55 to 0.60. Its evidence and metric deltas are recorded in
  `docs/evidence/IBEX_TEACHING_PARAMETER_COMPARISON_20260912.md`; the browser
  still needs an end-to-end live-service verification of both runs.

## OpenROAD-MCP intake

- The official OpenROAD-MCP repository was reviewed and locally built at the
  pinned commit `9dc80d3706fbcd8144cccb639fa21af7b933cbf5` (npm `1.1.0`).
- On the platform host, its TypeScript build and stdio `initialize` /
  `tools/list` probe passed after rebuilding the native `node-pty` module.
- Intake evidence is recorded in
  `docs/evidence/OPENROAD_MCP_INTAKE_20260913.md`; the integration architecture
  is recorded in ADR-002. Direct unauthenticated HTTP exposure remains out of
  scope.
