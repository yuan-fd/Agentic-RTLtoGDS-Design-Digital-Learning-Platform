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

## Evidence

- `python3 -m pytest -q`: `841 passed, 1 deselected` on the inherited primary
  environment.
- `python3 scripts/run_v2_frontend_suite.py --output /tmp/teaching-frontend-suite-20260911 --repeats 1`:
  compile, simulation and lint all passed for the fixed v2 RTL suite.
- Focused dashboard/doctor/web tests: `19 passed` across the executed test
  selections.
- `node --check apps/web/assets/app.js` and Python compile checks passed.

## Current next slice

Next: pass the selected mode through the existing L1 experiment creation
request and apply mode-specific custom-design/objective/hypothesis gates.
