# Slice 020 — L1-to-L2 durable controller handoff

## Intended architectural change

Consume one evidence-backed L1 escalation authorization into exactly one
durable L2 controller checkpoint. Repeated requests for the same observed L1
state return the same reflection, authorization, optimization request, and
pipeline identity. The product allowlist now names the complete
`orfs-agent/optimizer.l2.upstream-full-12d` capability rather than the broad
historical proposal capability.

This slice authorizes and creates the controller record only. Its initial
state is `authorized`; it does not submit an optimizer or candidate task.

## Files changed

- `packages/contracts/src/openroad_platform_contracts/product_surface.py`
- `packages/scheduler/src/openroad_platform_scheduler/l2_handoff.py`
- `packages/scheduler/src/openroad_platform_scheduler/l2_handoff_store.py`
- `apps/l1_workbench/service.py`
- `tests/test_product_surface.py`
- `tests/test_l2_handoff.py`
- `tests/test_l1_l2_authorization.py`
- `tests/test_l1_escalation_gate.py`
- this evidence record

## Before and after dependency edge

Before: `l2_escalate()` appended a fresh reflection and returned request data;
no controller consumed it, and repeated calls could mint independent
authorizations.

After: the Workbench reuses an existing authorization for the same state,
constructs a stable request, verifies the admitted full-12-D manifest, and
passes the typed records through `OptimizationHandoffService` to
`PipelineCheckpointStore`. `L2HandoffStore` binds the authorization to the
pipeline. A retry after a crash between checkpoint creation and binding uses
the authorization as the unique checkpoint subject and recovers the same
pipeline.

## Acceptance evidence

Focused tests cover product capability rejection, forged authorization
rejection, one-shot Runtime compatibility, a simulated unbound claim recovery,
and two Workbench escalation calls producing exactly one pipeline. The
controller checkpoint persists the complete request, authorization, frozen
Goal, and source DesignState.

## Protected components and unrelated behavior

No ORFS run, optimizer proposal, candidate execution, evaluator rule, RTL,
PDK, SDC, or existing trace was changed. The former broad capability remains
in the plugin manifest only for historical callers; it is no longer eligible
for the product L2 role.

## Rollback

Revert only the files listed above. Existing checkpoint and authorization
records must remain as historical evidence; do not delete their SQLite files.
