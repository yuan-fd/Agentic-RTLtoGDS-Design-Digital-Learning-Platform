# L1 natural-language EDA interaction: research, reuse decision, and requirements

Status: ACTIVE design baseline (2026-09-02)  
Scope: L1 only. This is not an L2 optimizer, a white-box repair system, or a UI implementation.

## Decision

The L1 product is a typed, evidence-backed control plane for an EDA engineer:

```text
user language -> GoalDraft / required clarifications -> immutable DesignGoal
-> typed plan -> Policy Gate -> SemanticToolCall -> Runtime / admitted plugin
-> artifact-backed ToolReceipt -> DesignState reducer -> durable audit trace
```

An LLM is a replaceable compiler/planner/diagnostician. It is never a shell
generator, an EDA process owner, a parser of record for raw logs, or the
authority for QoR and run state.

The existing Web workspace remains `LEGACY`. No new dashboard work starts
until the interfaces and durable trace below have a bounded real-flow smoke.

## Tutorial-proposal requirements extracted locally

Authoritative local teaching sources:

- `/share/home/yuanwenjie/tool-interact/EDA_Tool_Using_Agent_自然语言交互_OpenROAD_Tutorial.html`, sections 5--35;
- `/share/home/yuanwenjie/tool-interact/薄平台_外部插件_AI4EDA平台_代码架构与审计规划.html`, sections 8--21; and
- `ASPDAC27-AgenticEDA-Tutorial-zhiangwang-submitted.pdf` (kept as supplied primary material; this host lacks `pdftotext`, so no claim is made that its full text was machine-extracted).

The tutorial requires five semantic tool classes: query, configuration,
execution, comparison, and evidence. Its first 12-tool target is
`get_design_summary`, `query_timing`, `query_congestion`, `query_drc`,
`query_power`, `query_stage_metrics`, `get_artifact_excerpt`,
`set_flow_params`, `run_stage`, `run_full_flow`, `compare_runs`, and
`stop_or_escalate`.

Every tool must declare version, input/output schemas, preconditions,
postconditions, side effect, evidence requirement, permission level, and
backend capability. A successful mutation is a Runtime-accepted operation,
not a claimed QoR result. Only an artifact-backed observation can advance the
authoritative `DesignState`.

Required clarification fields are design/workspace, platform/toolchain,
intent, target metric/corner, protected SDC/clock decision, hard constraints,
allowed action scope, and budget. Missing safety- or QoR-relevant values are
blocking questions; safe display defaults must be recorded explicitly.

The tutorial's trace minimum is:

```text
goal id + input/state hash + planner rationale/evidence refs + typed call
+ policy verdict + Runtime/Plugin receipt + output evidence refs + state hash
```

Facts (measured metrics, artifact references, terminal state) must remain
distinct from hypotheses and LLM explanations.

## 2025--2026 landscape review

These sources were inspected as design evidence on 2026-09-02. They are not
admitted executable dependencies.

| Work / upstream | Relevant finding | L1 adoption decision |
| --- | --- | --- |
| [Agentic Electronic Design Automation: A Handoff Perspective (2026)](https://arxiv.org/abs/2606.19795) | Proposes handoff validity and a five-layer protocol spanning discovery, messages, invocation, orchestration, security/IP. | Adopt the handoff principle: every L1 boundary carries typed input, consumer acceptance, provenance, and evidence. Do not import an implementation without intake. |
| [Trace2Skill (2026)](https://arxiv.org/abs/2605.21810) | Builds reusable skills from verifier-grounded successful and failed traces; keeps dense verifier feedback bounded. | Adopt bounded feedback and trace-to-procedural-memory promotion gates only. It is L3/L4-adjacent; do not import its RTL editing policy into L1. |
| [LEGO skill platform (2026)](https://arxiv.org/abs/2604.23355) / [source](https://github.com/loujc/LEGO-An-LLM-Skill-Based-Front-End-Design-Generation-Platform) | Uses independent, composable skills in an FSM and reports open source availability. | Evaluate later as source-audit-only for a *frontend RTL skill* adapter. It must not replace the platform's Goal/Tool/Runtime contracts or become an executable plugin without commit/license/native-smoke intake. |
| [ChipLingo (2026)](https://arxiv.org/abs/2604.27415) | Finds domain RAG and instruction alignment useful for tool knowledge, while not treating retrieval as execution authority. | Adopt the separation: documentation/RAG may support explanation and planning; Registry/Policy remains the only execution path. No model training is in scope. |
| [EDATracer (2026 preprint)](https://arxiv.org/abs/2608.04032) | Organizes source, scripts, logs, netlists and reports for artifact-grounded analysis. | Adopt loss-aware evidence pointers and raw-artifact retention. Verify its upstream source/commit/license before any reuse. |
| [AgenticPD (2026 preprint)](https://arxiv.org/abs/2607.04758) | EDA proposal producer with black-box integration relevance. | Already classified source-audit/proposal-only in this repository; not an L1 control-plane dependency. |
| [OpenROAD-flow-scripts](https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts) | Native OpenROAD/ORFS flow boundary and stage artifacts. | Reuse only through a pinned toolchain profile and bounded adapters; L1 never exposes its Make/Tcl surface to a model. |
| [ORFS-Agent](https://github.com/ABKGroup/ORFS-Agent) | External L2 candidate-selection project, BSD-3-Clause. | Retain as the admitted L2 plugin candidate, outside L1 implementation. L1 only requests its registered capability. |

The review confirms the platform's existing `Reuse > Adapt > Reimplement`
policy. There is no safe drop-in project that supplies our required
OpenROAD-specific authority boundaries. We therefore reuse external projects
as narrow adapters and standards, while implementing only the missing control
plane contracts. No external code is installed, copied, executed, or
registered by this document.

## Gap matrix at baseline

| Requirement | Existing state | Required slice |
| --- | --- | --- |
| `DesignGoal`, `DesignState`, `SemanticToolCall`, `ToolReceipt` | Present in `packages/contracts`; no reverse runtime/plugin imports. | Preserve, add only versioned missing fields through a compatibility migration. |
| 12-tool tutorial surface | 11 names exist; `create_experiment` and L2 `propose_search_policy` are present, but `get_design_summary`, `query_stage_metrics`, and `run_full_flow` are missing; current handlers are not all Runtime-backed. | L1-S1/S3. |
| Clarification-aware natural-language compiler | Historical regex compiler only; no GoalDraft/Question/LLM adapter. | L1-S1 then L1-S5. |
| Policy-visible schemas and pre/postconditions | Semantic policy validates arguments, but registry definitions lack the full public contract and capability negotiation. | L1-S1. |
| Durable trace | No canonical append-only L1 trace store, event schema, replay endpoint, or state hash lineage. | L1-S2. |
| Runtime-backed query/execute tools | Partial in-process L1 bridge; process-local state is explicitly non-product. | L1-S3. |
| Plan/validate/execute/observe loop | No durable orchestrator or reducer. | L1-S4. |
| RAG / model provider | No L1 provider boundary; existing historical UI traces are not canonical. | L1-S5. |
| Real acceptance | No tutorial-shaped three-turn, artifact-backed OpenROAD smoke. | L1-S6. |
| Dashboard | Legacy UI only. | L1-S7, after L1-S6 passes. |

## Implementation order and acceptance

1. **L1-S1 — contracts and semantic registry.** Add `GoalDraft`, typed
   clarification questions/answers, tool schemas/capabilities, and the missing
   tutorial tool names. Keep `packages/contracts` dependency-free. Test schema
   rejection, protected assets, missing clarifications, and no shell fields.
2. **L1-S2 — durable trace and state reducer.** Create append-only trace events
   with deterministic state/input hashes and evidence references. Runtime stays
   the run/attempt authority. Test replay, tamper rejection, and fact versus
   hypothesis separation.
3. **L1-S3 — Runtime semantic adapters.** Implement read-only artifact/query
   adapters and controlled `set_flow_params`/stage/full-flow submission using
   registered capabilities. Eliminate process-local L1 authoritative state.
   Test pre/postconditions and a bounded Runtime smoke.
4. **L1-S4 — workflow loop.** Add a deterministic workflow executor that
   persists `plan -> validate -> accepted -> observed -> stop/escalate` and
   never embeds optimizer logic. Test recovery and budget stops.
5. **L1-S5 — replaceable LLM/RAG adapter.** A structured-output provider may
   produce only GoalDraft/clarifications/tool proposals. RAG supplies cited
   knowledge but has no write path. Test malformed/malicious outputs and
   provider-independent deterministic finalization.
6. **L1-S6 — tutorial acceptance.** On one pinned, verified RTL/toolchain run:
   parse a natural-language diagnostic request, execute at least a query and a
   permitted stage run, consume observed evidence, and produce a second
   evidence-cited action/stop decision. Preserve raw artifacts and trace.
7. **L1-S7 — trace workspace.** Render only stored L1 facts: user request and
   Goal IR, tool/policy/Runtime timeline, state/evidence, and reasoning
   summaries with source refs. No business controls or authoritative state in
   the browser.

Every slice is one migration boundary, receives focused tests and (where a
tool is involved) a bounded smoke, records exact changed files and rollback,
then undergoes an independent merge-gate audit. A failure returns to the slice
implementation; it does not relax an assertion or silently use a legacy path.

## Non-negotiable exclusions

- no model-generated shell, Tcl, Make, paths, environments, credentials, or
  arbitrary source edits;
- no replacement of Runtime, evaluator, artifact provenance, or plugin-native
  algorithms;
- no local BO/GP/repair policy hidden in L1;
- no L2 optimization, L3 repair, L4 source evolution, or TaiWei 3D coupling;
- no dashboard-derived state or UI-only trace; and
- no external executable integration without the repository intake gate.

## Rollback

This slice is documentation only. Revert its commit; it changes no runtime
behavior, source lock, toolchain, benchmark, evaluator, or historical data.
