# L1 Workbench vertical slice

This is the operational seed of the L1 Workbench, not the frozen trace
dashboard. It composes `L1SessionService`, `L1TraceService`,
`L1DurableLoop`, `L1RuntimeBridge`, and `WorkflowRuntime`; the HTTP handler
only transports requests and renders stored facts.

## Real EDA profiles

The default `smoke` backend exists only for API tests.  To run the managed
AES/Sky130HD reference that can legitimately hand off to the full ORFS-Agent
L2, select the operator-owned paper profile and an empty state root:

```bash
PYTHONPATH=packages/contracts/src:packages/scheduler/src:packages/execution/src:packages/analysis/src:. \
  .tools/venvs/orfs-agent/bin/python apps/l1_workbench/server.py \
  --state-root /tmp/openroad-l1-aes-workbench \
  --port 8766 \
  --backend orfs \
  --managed-reference orfs-agent-paper-aes-sky130hd \
  --orfs-agent-paper-orfs /absolute/orfs-ce8d36a-clean \
  --orfs-agent-openroad-bin /absolute/paper/OpenROAD/bin/openroad \
  --orfs-agent-yosys-bin /absolute/paper/yosys/bin/yosys \
  --orfs-agent-paper-environment /absolute/reviewed-paper-environment.json
```

This profile freezes the complete seven-file AES RTL bundle, the byte-identical
paper 4.5 ns SDC, Sky130HD, paper ORFS commit `ce8d36a7`, toolchain identity,
20% utilization, 0.60 placement density, `finish`, and the protected evaluator.
`--managed-reference` is mutually exclusive with `--rtl`; none of these inputs
come from the model, browser, or natural-language request.

The older mux teaching fixture remains available as an explicitly supplied
single-file L1 exercise, but it is not compatible with the AES L2 handoff:

```bash
PYTHONPATH=packages/contracts/src:packages/scheduler/src:packages/execution/src:. \
  .tools/venvs/orfs-agent/bin/python apps/l1_workbench/server.py \
  --state-root /tmp/openroad-l1-orfs-workbench \
  --port 8766 \
  --backend orfs \
  --rtl tests/fixtures/p2_mux_2to1.v \
  --top mux_2to1 \
  --platform nangate45 \
  --clock-period-ns 10
```

This startup selection is also operator-owned. It freezes
`tutorial_mux/mux_2to1`, the RTL hash, `nangate45`, 10 ns, `finish`, and the
bounded baseline parameter allowlist before it can submit a task. The L2 gate
must reject it when the configured campaign is AES/Sky130HD.

## Language front-end (`--goal-provider`)

The operator chooses the natural-language front-end at server start:

- `tutorial` (default): the deterministic managed-profile parser — inspectable,
  offline; it renders the operator-selected mux or AES design context.
- `codex`: the managed Codex CLI (`gpt-5.6-terra`, read-only sandbox, env
  allowlist) acting as a structured `GoalDraft` provider.  The model may only
  return typed language facts: it is decoded against the `L1ModelBoundary`
  allowlist and `GoalDraft` validation, and a failed or off-schema reply
  raises instead of silently falling back.

```bash
PYTHONPATH=packages/contracts/src:packages/scheduler/src:packages/execution/src:. \
  .tools/venvs/orfs-agent/bin/python apps/l1_workbench/server.py \
  --state-root /tmp/l1-codex-workbench --port 8766 --goal-provider codex
```

Run it with:

```bash
PYTHONPATH=packages/contracts/src:packages/scheduler/src:packages/execution/src:. \
  .tools/venvs/orfs-agent/bin/python apps/l1_workbench/server.py \
  --state-root /tmp/l1-workbench --port 8766
```

Routes (each reads or mutates the durable Session through the same Policy and
Runtime boundary):

- `POST /api/l1/sessions` `{ "text": "Run one bounded implementation flow." }`
- `POST /api/l1/sessions/{session_id}/answers` with typed clarification answers
- `POST /api/l1/sessions/{session_id}/execute` with a bounded visible decision summary
- `POST /api/l1/sessions/{session_id}/m1-proposal` creates the baseline-fact-backed registered parameter proposal
- `POST /api/l1/sessions/{session_id}/candidates` consumes that exact durable proposal in a Runtime candidate
- `POST /api/l1/sessions/{session_id}/m1-compare` compares the two Runtime observations and records the M1 stop decision
- `POST /api/l1/sessions/{session_id}/advance` for the evidence-backed tutorial step
- `POST /api/l1/sessions/{session_id}/l2-escalate` for the visible L1→L2 authorization gate
  (requires two measured Runtime observations; records `escalate` and freezes an
  `OptimizationRequest` — it never submits ORFS-Agent execution)
- `POST /api/l1/sessions/{session_id}/l2-configure` freezes the admitted full
  12-D domain, ECP/DWL/COMBO objective set, design/PDK/toolchain receipts,
  full campaign budget, and independent seeds on that authorization
- `POST /api/l1/sessions/{session_id}/l2-advance` performs a scheduling-only
  checkpoint transition; the handler always forces `execute=false` and never
  runs an EDA process in the HTTP request
- `GET /api/l1/sessions/{session_id}/l2-campaigns` and
  `GET /api/l1/sessions/{session_id}/l2-campaigns/{pipeline_id}` expose only
  Session-bound durable campaign state, Runtime IDs, observations, history,
  and evidence references for live monitoring
- `GET /api/l1/sessions/{session_id}/teaching` for a read-only per-event teaching replay
- `POST /api/l1/sessions/{session_id}/queries` for a typed timing/congestion/DRC/power/metrics read
- `POST /api/l1/sessions/{session_id}/knowledge` for a typed, Policy-gated
  ORAssistant query with `query`, `purpose=knowledge|error_explanation`, and
  `top_k`; Runtime citations are returned without consuming an EDA-run budget
- `POST /api/l1/sessions/{session_id}/artifacts` for an allowlisted excerpt
- `POST /api/l1/sessions/{session_id}/stages` for a permitted Runtime stage
- `GET /api/l1/sessions/{session_id}/events?after={sequence}`
- `POST /api/l1/sessions/{session_id}/cancel`
- `POST /api/l1/sessions/{session_id}/recover`

The smoke backend runs the full chain against a real `WorkflowRuntime`
subprocess adapter.  The `orfs` profile instead launches the admitted local
ORFS/OpenROAD backend.  In both cases the Runtime store records the process
receipt and artifacts; the L1 trace records the resulting facts.  The basic
trace is:

`goal_drafted → goal_finalized → tool_called → policy_decided(allow) →
tool_receipt → state_transition`.

The smoke adapter is an execution-protocol smoke, not an OpenROAD QoR claim.
The `orfs` profile is a real baseline EDA flow, not ORFS-Agent optimization:
ORFS-Agent remains an external L2 capability and is intentionally outside this
L1 workbench.
Cancellation uses Runtime's controlled cancel port; recovery resumes only the
durable session/plan records and never emits a duplicate Runtime submission.

## Diagnosis and cross-stage recovery boundary

L1 normalizes artifact-backed timing, congestion, DRC and power facts into
`StageAnalysis`/`DiagnosisReport`. Missing parser output remains unavailable;
an absent target remains unknown. A terminal Runtime failure before protected
QoR is represented by four unavailable domains plus the cited failure/artifact
evidence, never by invented metric values.

Recovery is also typed. A checkpoint restore must bind the durable recovery
decision, a previously verified direct-ancestor candidate and its exact RTL
SHA-256. The plan carries no source text, patch, parameter or shell command;
after selection, compile/lint, functional verification and ORFS are new Runtime
submissions. One real bounded backend-failure→RTL-checkpoint→GDS trajectory is
accepted at:

```text
var/evidence/platform-cross-stage-rtl-recovery-20260905-r2/summary.json
SHA-256 1606eb84083be453a9efe2e8b1cfa7986899089332d08059247f0250472bbf6d
```

This is a platform integration acceptance, not CLOSER-Bench and not a general
autonomous RTL-repair claim.

## Full A2-ORFO product campaign worker

After the API has returned an authorized `pipeline_id` and `l2-configure` has
frozen it, start the trusted worker against the same state root.  The worker is
the only Workbench composition that calls the full campaign controller with
`execute=true`; it does not depend on a Session, UI, mux profile, or L1 RTL.

```bash
PYTHONPATH=packages/contracts/src:packages/scheduler/src:packages/execution/src:packages/analysis/src:. \
  .tools/venvs/orfs-agent/bin/python apps/l1_workbench/a2_campaign_worker.py \
  --state-root /absolute/workbench-state \
  --a2-orfo-source /absolute/a2-orfo-8b20a3c-clean \
  --a2-orfo-model /absolute/mxbai-embed-large-v1-b33106f \
  --a2-orfo-python /absolute/a2-orfo-venv/bin/python \
  --a2-orfo-codex /absolute/platform-managed/codex \
  --orfs-agent-source /absolute/orfs-agent-730f1fa-clean \
  --orfs-agent-paper-orfs /absolute/orfs-ce8d36a-clean \
  --orfs-agent-openroad-bin /absolute/paper/OpenROAD/bin/openroad \
  --orfs-agent-yosys-bin /absolute/paper/yosys/bin/yosys \
  --orfs-agent-paper-environment /absolute/reviewed-paper-environment.json \
  --orfs-agent-python /absolute/orfs-agent-venv/bin/python \
  --pipeline-id pipeline-... \
  --max-parallel 4
```

The environment file is an operator-reviewed JSON string map containing only
the admitted library-path keys.  Omitting `--pipeline-id` scans all configured
nonterminal `a2-orfo-campaign-v1` checkpoints. `--once` advances at
most one transition; the default loop exits for a targeted pipeline only at
`completed`, `failed`, or `diagnosis_required`. Candidate failures and their
raw registered artifacts remain in campaign history and feed the next native
A2 step; only protected-evaluator artifact-backed objective rows are measured
QoR. The default protocol preserves 26 initial measurements and five rounds of
25 measurements (151 total) over all 12 parameters including variable `CLK`.
The older `l2_campaign_worker.py` serves only historical
`orfs-agent-full-campaign-v1` checkpoints and is not the product optimizer.

## Terminal dashboard

In a second terminal, run:

```bash
PYTHONPATH=packages/contracts/src:packages/scheduler/src:packages/execution/src:. \
  .tools/venvs/orfs-agent/bin/python apps/l1_workbench/terminal_dashboard.py
```

The terminal client is deliberately split: the left 65% is an Agent Harness
view of durable, visible execution facts; the right pane is the human Client
surface for requests, clarification answers, and control. It never displays
hidden chain-of-thought, raw provider transcripts, shell commands, secrets, or
workspace paths.

Commands include `:new <natural-language goal>`, `:answer <question_id> <answer>`,
`:baseline`, `:m1-propose`, `:candidate <proposal-id>`, `:compare <baseline-run-id>`,
`:advance` (one teaching step), `:explain` (loads the per-event teaching replay),
`:l2` (authorize the L1→L2 gate), `:pause`/`:resume` (replay rhythm),
`:cancel [reason]`, `:recover`, `:refresh`, and `:quit`.  It polls the cursor
API and displays only returned durable facts; it does not use a browser, local
trace, or local state.  The left-hand Harness is split into four teaching
panels: Goal/IR, Tool/Policy, Runtime DesignState/Evidence, and
Reflection/Replay.  The right-hand Client is the only input surface.

### A concrete teaching flow

With the real EDA tutorial profile above, try the following in the right-hand
**USER CLIENT** pane:

```text
Command> :new 帮我改善 mux 的 setup timing，但面积不能比 baseline 增加超过 3%，不许修改 RTL/SDC，最多跑 3 次。
```

The API creates a durable Session and records `goal_drafted`. The right pane
shows only the actually pending typed questions; for this request they are:

```text
permitted change scope and the managed baseline/corner. Answer them through
the same Session:
```

The operator answers it through the same Session:

```text
Command> :answer change_scope registered_parameters_only
Command> :answer design_context managed_mux_default_corner_baseline
```

The left **L1 AGENT HARNESS** pane then receives and renders the stored facts:

```text
#  0 GOAL DRAFT
      clarification requested
#  1 FROZEN GOAL IR
      objective=timing
```

Then use the real M1 evidence loop. Each action is visible, Policy-gated, and
persists a Runtime/trace fact:

```text
Command> :baseline
Command> :m1-propose
Command> :candidate <proposal-id shown by the right pane>
Command> :compare <baseline-run-id shown by the STATE panel>
```

The real acceptance sequence is (identifiers and timestamps vary):

```text
baseline run_full_flow → set_flow_params → candidate run_full_flow
→ compare_runs → reflection stop
```

For the `--backend orfs` profile, the final state is produced by real ORFS
stages (`synth → floorplan → place → cts → route → finish`) launched by
Runtime in an attempt-local workspace.  It retains the raw logs, GDS/DEF/ODB,
netlist, reports, metrics and content hashes.  This is a baseline EDA run, not
an L2 ORFS-Agent optimization campaign or a QoR-improvement claim.
