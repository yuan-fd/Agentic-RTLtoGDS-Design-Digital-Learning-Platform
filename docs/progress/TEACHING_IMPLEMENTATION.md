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
- Mode-specific request validation now rejects custom Guided fields, rejects
  hypotheses in Open Lab, and requires objective plus hypothesis for Challenge;
  accepted context is carried as TaskSpec labels.

## Evidence

- `python3 -m pytest -q`: `841 passed, 1 deselected` on the inherited primary
  environment.
- `python3 scripts/run_v2_frontend_suite.py --output /tmp/teaching-frontend-suite-20260911 --repeats 1`:
  compile, simulation and lint all passed for the fixed v2 RTL suite.
- Focused dashboard/doctor/web tests: `19 passed` across the executed test
  selections.
- `node --check apps/web/assets/app.js` and Python compile checks passed.

## Current next slice

Next: expose the mode catalog and context controls in the simplified Web
workspace, then add the first Open Lab copy-from-run flow.
