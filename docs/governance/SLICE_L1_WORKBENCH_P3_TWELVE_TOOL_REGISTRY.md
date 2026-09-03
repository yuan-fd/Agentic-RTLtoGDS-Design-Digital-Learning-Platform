# L1 Workbench P3: single Tutorial twelve-tool registry

## Boundary

`L1RuntimeToolRegistry` is the only dispatcher admitted into the durable L1
loop. It validates the fixed `TUTORIAL_L1_TOOLS` contract with
`L1SemanticToolPolicy` and delegates the typed call to `L1RuntimeBridge`.
Startup fails if the bridge does not declare exactly the same twelve tools.
The historical API is deliberately not used as a composition host for this
slice: its top-level imports still contain unrelated historical research
surfaces.  The clean `apps/l1_workbench` composition point is introduced in
P6, after the durable contracts have passed their isolated gates.

## Before and after dependency edge

Before, semantic calls had no single fixed tool registry.  After, every call
entering `L1DurableLoop` crosses one typed policy/registry boundary before the
Runtime bridge; Runtime remains the sole run authority and the trace owns the
audit sequence.  A future UI/API composition may not bypass this boundary.

## Explicit non-goals

The historical `semantic_tools.py` and `l1_orfs_service.py` retain their old
experiment/optimizer-oriented behavior solely as legacy material. They are not
imported by the new L1 loop and are not a fallback or compatibility route.
This slice does not reimplement an optimizer or alter Runtime/evaluator logic.

## Acceptance

Changed files: `l1_tool_registry.py`, `l1_loop.py`, the capability task-factory
ports, focused P3 tests, and this record. Tests prove exact 12-tool capability
discovery and concrete bridge dispatch mapping, rejection of incomplete
bridges, forbidden legacy calls, forged receipt identity, safe query
projection, and L1 durable-loop / Runtime-bridge regression in a clean
checkout.

## Rollback

Revert the registry, loop wiring, capability task-factory ports, P3 tests, and
this record. The old historical modules remain intact; no schema or protected
evaluator change occurs.
