# L1 Workbench P3: single Tutorial twelve-tool registry

## Boundary

`L1RuntimeToolRegistry` is the only dispatcher admitted into the durable L1
loop. It validates the fixed `TUTORIAL_L1_TOOLS` contract with
`L1SemanticToolPolicy` and delegates the typed call to `L1RuntimeBridge`.
Startup fails if the bridge does not declare exactly the same twelve tools.
The active verified-RTL promotion API is also migrated onto the durable chain:
typed draft → finalized Goal policy anchor → `L1DurableLoop` → Runtime receipt.

## Before and after dependency edge

Before, the active API constructed the historical in-process
`L1ORFSToolService`, created an experiment, and submitted a legacy
`experiment_id` call. After, it owns only composition of a trusted policy and
uses the new Registry through `L1DurableLoop`; Runtime remains the sole run
authority and the trace owns the audit sequence.

## Explicit non-goals

The historical `semantic_tools.py` and `l1_orfs_service.py` retain their old
experiment/optimizer-oriented behavior solely as legacy material. They are not
imported by the new L1 loop and are not a fallback or compatibility route.
This slice does not reimplement an optimizer or alter Runtime/evaluator logic.

## Acceptance

Changed files: `l1_tool_registry.py`, `l1_loop.py`, `apps/api/app.py`, the
P3 tests, and this record. Tests prove exact 12-tool capability discovery and
concrete bridge dispatch mapping, rejection of incomplete bridges,
`CREATE_EXPERIMENT`, and forged receipt identity, plus durable API promotion
trace/run identity and L1 durable-loop / Runtime-bridge regression.

## Rollback

Revert the registry, loop/API wiring, P3 tests, and this record. This removes
the API's two L1 SQLite stores only from future composition; it does not delete
their retained audit records. The old historical modules remain intact; no
schema or protected evaluator change occurs.
