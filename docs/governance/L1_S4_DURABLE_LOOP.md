# L1 S4 — durable Plan → Validate → Execute → Observe loop

## Intended boundary

S4 adds the scheduler-side orchestration record required to connect the S1
typed call, S2 trace/reducer, and S3 Runtime bridge.  It does not own a run,
attempt, artifact, metric, cancellation outcome, evaluator result, or
optimization policy.  Those remain Runtime/protected-component facts.

Before S4, a parameter proposal could be marked consumed before trace and
Runtime submission succeeded, and a plan retained the pre-patch tool call.
After S4, `L1LoopStore` persists a plan, atomically reserves a proposal,
persists the exact canonical call (including `proposal_id` and
`parameter_patch`) before bridge dispatch, then atomically commits the
receipt and proposal consumption.  Pre-submit failures release a reservation;
a local receipt-commit interruption is recovered from the already durable
S2 `tool_receipt` event without resubmitting Runtime work.

`STOP_OR_ESCALATE` is also now a real terminal loop: controlled cancellation
request → Runtime terminal `cancelled` observation → canonical reducer state
`stopped` → durable `STOPPED` trace fact.  The stop fact is a Runtime-backed
fact, never an LLM assertion.

## Dependency edge

```text
typed SemanticToolCall
  -> L1DurableLoop / L1LoopStore (intent + reservation + canonical call)
  -> L1TraceService (call, policy, receipt)
  -> L1RuntimeBridge -> Runtime
  -> RuntimeObservation -> L1StateReducer -> append-only trace
```

No API, web, Runtime, evaluator, external optimizer, RTL, PDK, SDC, or
historical evidence is changed by this slice.

## Changed files

- `packages/scheduler/src/openroad_platform_scheduler/l1_loop_store.py`
- `packages/scheduler/src/openroad_platform_scheduler/l1_loop.py`
- `packages/scheduler/src/openroad_platform_scheduler/l1_state_reducer.py`
- `packages/scheduler/src/openroad_platform_scheduler/l1_trace_service.py`
- `tests/test_l1_loop_store.py`
- `tests/test_l1_durable_loop.py`
- `tests/test_l1_runtime_bridge.py`
- `docs/evidence/l1_s4_bounded_smoke/` (captured smoke facts)
- this document

## Acceptance evidence

Focused suite:

```bash
PYTHONPATH=packages/contracts/src:packages/scheduler/src:packages/execution/src \
  .tools/venvs/orfs-agent/bin/python -m pytest -q \
  tests/test_l1_loop_store.py tests/test_l1_durable_loop.py \
  tests/test_l1_runtime_bridge.py tests/test_l1_trace_service.py \
  tests/test_l1_state_reducer.py
```

It covers trace-, bridge-, and receipt-persistence failure injection;
restart recovery from a durable receipt; exact canonical patch persistence;
and two bounded real Runtime smokes: ProcessAdapter execution and live
ProcessGuardian cancellation.  The cancellation smoke verifies the Runtime
run reaches `cancelled`, the reducer produces `stopped`, and the final trace
events are `state_transition`, `stopped`.

The captured bounded-smoke workspace, database and log locations are recorded
under `docs/evidence/l1_s4_bounded_smoke/` by the evidence command run for
this slice; its file SHA-256 values and terminal status appear in
`MANIFEST.sha256` and `RESULT.txt` there.  These are smoke artifacts only,
not QoR claims.

## Rollback

S4 prior commits, newest first, are:

```text
525c19a f86b3a2 05ccad6 70fab6c fe28ec6 9e41e94 157384a 3f7634d 9afaada
```

To roll back the completed S4 commit, revert that single completion commit
(the commit containing this document) first, then run `git revert` on the
listed commits in the displayed newest-to-oldest order as far back as the
desired pre-S4 boundary.  Do not reset or delete historical paths.  Re-run
the focused suite after every revert.
