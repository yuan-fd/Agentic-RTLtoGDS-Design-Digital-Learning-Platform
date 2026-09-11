# Teaching migration progress

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

## Current next slice

Next: validate the connected route in a browser and with a bounded smoke, then
connect Rule Batch and A2 campaign actions to the teaching UI without
weakening their native protocols.
