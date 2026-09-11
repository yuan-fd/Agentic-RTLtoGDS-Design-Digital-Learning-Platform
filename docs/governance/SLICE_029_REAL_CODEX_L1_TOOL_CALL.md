# Slice 029 — real Codex L1 semantic tool call

## Problem

The managed Codex provider had real evidence for the `GoalDraft` boundary, but
the next-action path had only provider-fixture tests. A first probe against the
accepted AES session failed before invoking Codex: `_model_knowledge_hits`
invented a `trace-event:` reference for a proposal-only trace event with no
artifact evidence, while the public `EvidencePointer` contract correctly
rejects that reference scheme.

## Intended boundary

Expose only already-valid durable evidence to the untrusted model. A trace
event without an artifact/run evidence pointer remains in the canonical trace,
but is not promoted into the model's retrieval packet. This does not change
the trace schema, weaken evidence validation, add a reference type, or grant
the model an execution port.

Changed files:

- `apps/l1_workbench/service.py`
- `tests/test_l1_codex_tool_loop.py`
- `scripts/run_l1_codex_tool_call_smoke.py`
- this record

Before: `uncited durable trace event -> invented trace-event EvidencePointer
-> public-contract rejection`.

After: `artifact-backed DesignState/events -> L1KnowledgeHit -> real Codex
typed proposal -> Policy -> bounded tool receipt`; uncited events stay visible
in the trace but are omitted from the model packet.

## Acceptance

Focused regression:

```text
8 passed in 5.88s
```

Real evidence:

- directory: `var/evidence/l1-codex-tool-call-20260904-r1`;
- summary SHA-256:
  `e0b2b89ea662e03632314b826fe13a2649b6f01437ec9a8c026492c5c781a5c6`;
- provider/model: `codex-cli-l1-goal-v1`, `gpt-5.6-terra`;
- CLI: `codex-cli 0.147.0`, ephemeral read-only sandbox, no fallback;
- same accepted AES session/Goal and baseline Runtime run
  `4934a4baebe74ac0bb5943a37a24942a`;
- Codex selected `query_timing`, copied the Runtime-assigned call/Goal/state
  identities, and cited the sole protected-evaluator report artifact;
- cited artifact SHA-256 was reread and matched
  `3c6a24480ccd636f4ef1fdd95ce28fcafeecadca15cca7c1a6ed919c80f731b7`;
- Policy accepted the call and the tool returned the measured setup WNS
  `-0.240581 ns` with terminal Runtime status `succeeded`;
- trace tail is `state_transition -> tool_called -> policy_decided ->
  tool_receipt`;
- Runtime run count remained one before and after: no new EDA run was created.

This proves one real natural-language-model next-action interaction over stored
EDA evidence. It does not claim that every model reply succeeds, that the model
can execute arbitrary tools, or that the queried design meets timing.

## Protected components and rollback

No RTL, SDC, PDK, ORFS/ORFS-Agent source, toolchain, evaluator, L2 domain,
candidate, objective, seed, or budget changed. Revert the three implementation,
test, and smoke-runner files to restore the old failing retrieval behavior.
Preserve the evidence directory as historical evidence even after rollback.
