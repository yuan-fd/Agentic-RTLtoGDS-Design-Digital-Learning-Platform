# L1 S7 — fact-only Trace Dashboard

S7 adds a standalone read-only dashboard at `apps/l1_trace_dashboard/`.  It
does not alter the legacy web application or API.  Its only data source is
`L1TraceStore`, whose `read()` validates the append-only hash chain before
`l1_trace_projection` turns stored events into JSON.

The UI shows the tutorial-required layers: goal/Goal IR events, typed calls
and policy verdicts, Runtime receipts/state transitions, evidence references,
and a chronological trace.  Planner material is explicitly labelled
**Reasoning summary (not hidden chain-of-thought)**.  Runtime facts and
hypotheses are rendered separately.  There are no mutation controls, model
providers, generic command fields, evaluator results, or browser-owned state.

Run it against an existing durable trace:

```bash
PYTHONPATH=packages/contracts/src:packages/scheduler/src:packages/execution/src \
  .tools/venvs/orfs-agent/bin/python apps/l1_trace_dashboard/server.py \
  --trace-db docs/evidence/l1_s6_tutorial_smoke/test_tutorial_shaped_language_0/trace.sqlite
```

Then open `http://127.0.0.1:8765`.  The API surface is read-only:
`GET /api/traces` and `GET /api/traces/{trace_id}`.

Changed files: `l1_trace_projection.py`, the isolated dashboard server/assets,
`tests/test_l1_trace_projection.py`, and this document.  Runtime, evaluator,
external algorithms and legacy `apps/web` are unchanged.

Acceptance: projection/trace/tutorial tests plus the HTTP smoke against the
captured S6 trace; it must return `trace-1`, ten durable events, terminal
`reflection_recorded` with recorded decision `stop`, and the static dashboard.

Rollback: revert the S7 completion commit.  It has no schema migration,
Runtime mutation, external side effect, or dependency installation.
