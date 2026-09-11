# Slice 033: L1 ORAssistant typed knowledge service

## Boundary

This slice adds one read-only `query_openroad_knowledge` semantic tool to L1.
The tool accepts only `query`, `purpose`, and `top_k`; Policy validates it,
Runtime executes the already-admitted pinned ORAssistant plugin, and the L1
receipt cites Runtime-registered artifacts. It neither executes EDA nor enters
the QoR state reducer.

The slice does not change ORAssistant retrieval, any EDA flow, protected QoR,
the UI, an optimizer, or the frozen A2-ORFO/RTLScout acceptance protocols.

## Before / after dependency edge

Before:

```text
Workbench model context -> locally projected state/trace summaries
ORAssistant -> Runtime-only standalone acceptance
```

After:

```text
SemanticToolCall(query_openroad_knowledge)
  -> L1SemanticToolPolicy
  -> plugin-neutral KnowledgeTaskFactory contract
  -> Runtime -> pinned ORAssistant BM25
  -> registered retrieval/explanation/provenance artifacts
  -> cited ToolReceipt -> durable L1 trace
```

Scheduler imports only dependency-free knowledge contracts. The concrete
ORAssistant factory is selected in the Workbench composition root and is
authorized by `ProductRole.OPENROAD_KNOWLEDGE`.

## Changed files

- `packages/contracts/src/openroad_platform_contracts/agent_control.py`
- `packages/contracts/src/openroad_platform_contracts/l1_tool_contract.py`
- `packages/contracts/src/openroad_platform_contracts/task_factory.py`
- `packages/contracts/src/openroad_platform_contracts/product_surface.py`
- `packages/contracts/src/openroad_platform_contracts/__init__.py`
- `packages/execution/src/openroad_platform_execution/orassistant_plugin.py`
- `packages/execution/src/openroad_platform_execution/__init__.py`
- `packages/scheduler/src/openroad_platform_scheduler/l1_semantic_policy.py`
- `packages/scheduler/src/openroad_platform_scheduler/l1_runtime_bridge.py`
- `packages/scheduler/src/openroad_platform_scheduler/l1_tool_registry.py`
- `apps/l1_workbench/service.py`
- `apps/l1_workbench/server.py`
- `apps/l1_workbench/README.md`
- `scripts/run_l1_orassistant_knowledge_acceptance.py`
- `tests/test_l1_orassistant_knowledge.py`
- focused existing contract, registry, bridge, plugin and product tests

## Focused tests

```text
39 passed
```

The tests cover the generic factory, exact semantic arguments, no URL/path/
command input, Policy and Runtime execution, artifact-backed citations, trace
events, product-role admission, and preservation of the EDA-run budget.

## Real bounded acceptance

Canonical artifact:

```text
var/evidence/l1-orassistant-typed-knowledge-20260905-r1/summary.json
SHA-256 7c9331b4517280392c2dbdd8345aa5ed693f46596158c4f54528d8e92f4a9a04
Runtime run 52540f005fb14d5f98d00b00dc2ddbb7
accepted true
```

The real Workbench request asks for an explanation of
`[WARNING DRT-0349]`. The trace ends in
`tool_called -> policy_decided(allow) -> tool_receipt`; Runtime executes only
`orassistant`, registers all four required artifacts, and the receipt carries
document/chunk hashes plus an `artifact:runtime-*` citation. The state retains
all three EDA runs. The response explicitly says retrieval is not a diagnostic
claim and lists required run-context checks.

This proves one cited integration path, not root-cause diagnosis quality or
broad retrieval accuracy.

## Protected and unrelated behavior

No RTL, PDK, SDC, toolchain, evaluator, DSE domain, campaign protocol, or
upstream source changed. Raw ORAssistant artifacts remain under Runtime;
public L1 trace fields use `source_document`/`source_reference` and registered
artifact hashes rather than exposing an execution workspace path.

## Rollback

Remove `QUERY_OPENROAD_KNOWLEDGE`, the generic knowledge request/factory and
product role; remove its bridge/composition/HTTP branch, acceptance script and
tests; restore the previous tutorial tool set. The existing standalone
ORAssistant plugin and Slice 032 evidence remain valid and untouched.
