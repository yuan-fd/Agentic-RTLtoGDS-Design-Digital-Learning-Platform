# L1 Workbench P2: durable language session and event cursor

## Boundary

Add a durable L1 Session head for natural-language GoalDraft interpretation,
typed clarification answers, deterministic Goal IR finalization, and cursor
based retrieval of the existing append-only trace. This is not a tool or
Runtime submission API.

## Ownership

- `L1SessionService` owns session-head staging and recovery of language/Goal
  transitions only.
- `L1TraceStore` remains the append-only event authority.
- `GoalFinalizer` still supplies the deterministic trusted-policy boundary.
- Runtime remains the sole authority for future execution and state facts.

## Recovery

The store writes a `creating` head before a trace append. `recover()` resumes
only the missing draft/goal trace transition; it cannot submit a SemanticTool,
create a TaskSpec, or operate Runtime. Goal identifiers are deterministic from
the session identity, allowing a crash after goal append to be reconciled
without duplicate finalization.

## Acceptance

Focused tests cover clarification-required → answered → finalized, durable
restart readback, cursor event retrieval, invalid answer rejection, and staged
recovery. No API/UI, Runtime, evaluator, plugin, or legacy SpecConversation
path changes in this slice.

## Rollback

Revert the new L1 Session contract/service/test and this record. Existing
trace schema and existing session systems are untouched.
