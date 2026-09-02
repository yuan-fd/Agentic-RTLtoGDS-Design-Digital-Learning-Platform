# L1 S5 — replaceable structured model and RAG boundary

## Intended boundary

S5 introduces `L1ModelBoundary`, a scheduler-side decoder for an injected
structured-output provider and a read-only knowledge retriever.  It has no
model SDK, network client, subprocess, shell/Tcl field, plugin registration,
or Runtime mutation path.

The provider may propose only an existing `GoalDraft` or `SemanticToolCall`.
The boundary fixes the parser identity, preserves the exact user request,
rejects unsafe fields recursively, restricts response shape, validates every
call with the finalized `DesignGoal` policy, and never invokes a bridge or
Runtime.  Retrieval returns bounded excerpts with durable `EvidencePointer`s.
Those pointers may explain a proposal but cannot grant tool permission; every
citation and call evidence reference must be one returned by that retriever.

Before: a caller would have to decide how to decode any model/retrieval
payload, risking a model-specific execution edge.  After:

```text
untrusted provider JSON -> L1ModelBoundary -> existing typed contracts
untrusted retriever      -> cited L1KnowledgeHit -> planner context only
typed call -> L1SemanticToolPolicy -> S4 loop -> Runtime
```

## Changed files

- `packages/scheduler/src/openroad_platform_scheduler/l1_model_boundary.py`
- `tests/test_l1_model_boundary.py`
- this document

Runtime, protected evaluator, execution packages, external optimizer
algorithms, and historical evidence are unchanged.

## Acceptance evidence

```bash
PYTHONPATH=packages/contracts/src:packages/scheduler/src:packages/execution/src \
  .tools/venvs/orfs-agent/bin/python -m pytest -q \
  tests/test_l1_model_boundary.py tests/test_l1_goal_draft_contracts.py \
  tests/test_l1_goal_finalizer.py tests/test_l1_tool_contracts.py
```

The tests use an in-process deterministic fixture provider/retriever, not an
external executable integration.  They prove provider-independent typed
draft decoding, request immutability, recursive shell rejection, rejection of
uncited retrieval claims, and final policy validation of the proposed tool.
S6 will provide the first actual provider-to-S4-to-Runtime tutorial smoke.

## Rollback

Revert the single S5 completion commit containing this document.  No schema,
Runtime state, external project, or protected experiment input requires data
migration or cleanup.
