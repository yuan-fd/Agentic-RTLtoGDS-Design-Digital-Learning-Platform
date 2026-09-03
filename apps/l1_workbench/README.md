# L1 Workbench vertical slice

This is the operational seed of the L1 Workbench, not the frozen trace
dashboard. It composes `L1SessionService`, `L1TraceService`,
`L1DurableLoop`, `L1RuntimeBridge`, and `WorkflowRuntime`; the HTTP handler
only transports requests and renders stored facts.

## Real EDA tutorial profile

The default `smoke` backend exists only for API tests.  To run the managed
local ORFS/OpenROAD toolchain through the very same L1 Session, use the frozen
`p2_mux_2to1.v` tutorial RTL and an empty state root:

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

This startup selection is operator-owned, not an LLM or browser field.  It
uses the admitted `orfs` plugin and local managed toolchain.  The Session
freezes `tutorial_mux/mux_2to1`, the RTL hash, `nangate45`, 10 ns, `finish`,
and the bounded baseline parameter allowlist before it can submit a task.

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
- `POST /api/l1/sessions/{session_id}/queries` for a typed timing/congestion/DRC/power/metrics read
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
`:baseline`, `:m1-propose`, `:candidate <proposal-id>`, and `:compare <baseline-run-id>`.
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
