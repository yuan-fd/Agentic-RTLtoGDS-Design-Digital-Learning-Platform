# L1 S7 Hands-on dashboard acceptance

## Migration slice

- Boundary: read-only L1 teaching projection and the durable facts needed to
  explain the Tutorial Proposal flow.
- Changed files: `packages/contracts/src/openroad_platform_contracts/l1_trace.py`,
  `packages/scheduler/src/openroad_platform_scheduler/l1_trace_service.py`,
  `apps/l1_trace_dashboard/app.js`, and focused L1 tests.
- Dependency edge: the Dashboard continues to depend only on the SQLite
  read-only projection.  The scheduler writes trace facts; neither Dashboard
  nor contracts imports Runtime, a plugin, or an optimizer.

## Bounded smoke evidence

- Command: `pytest --basetemp docs/evidence/l1_s7_teaching_smoke
  tests/test_l1_tutorial_smoke.py`
- Terminal status: `1 passed`; the fixture Runtime observation is `succeeded`
  and the L1 state transition is `running -> observed`.
- Trace: `docs/evidence/l1_s7_teaching_smoke/test_tutorial_shaped_language_0/trace.sqlite`
- SHA-256: `cd0fde8c4720e2c6358e947048b98b7a053ae745cc74c84593213d0a5c9b5d73`
- HTTP acceptance: `GET /api/traces/trace-1` returned 10 verified events,
  including user request, clarification arrays, final Goal IR, policy identity,
  Runtime receipt, before/after DesignState, and reflection basis event IDs.

## Teaching and safety assertions

The four panels render: (1) user request / clarification / final Goal IR,
(2) typed tool call → policy → receipt, (3) verified DesignState deltas and
evidence, and (4) fact-backed decision, explicitly separate from unverified
hypotheses.  Planner-visible summaries are constrained to a short single-line
conclusion and reject hidden-reasoning and secret-like markers before durable
storage.  The collapsed audit shows only event and evidence references, not a
raw Runtime payload.

## Rollback

Revert this migration's files and restart the standalone Dashboard with the
prior trace database.  Runtime, evaluator, plugins, and the historical Web UI
are unchanged.
