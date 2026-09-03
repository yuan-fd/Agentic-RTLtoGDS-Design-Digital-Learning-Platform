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

Routes:

- `POST /api/l1/sessions` `{ "text": "Run one bounded implementation flow." }`
- `POST /api/l1/sessions/{session_id}/answers` with typed clarification answers
- `POST /api/l1/sessions/{session_id}/execute` with a bounded visible decision summary
- `GET /api/l1/sessions/{session_id}/events?after={sequence}`
- `POST /api/l1/sessions/{session_id}/cancel`
- `POST /api/l1/sessions/{session_id}/recover`

The integration test runs the full chain against a real `WorkflowRuntime`
subprocess adapter. Its artifact is `l1_tool_receipt.txt`; the adapter command
has Runtime-recorded exit code `0`. The resulting trace is:

`goal_drafted → goal_finalized → tool_called → policy_decided(allow) →
tool_receipt → state_transition`.

The bounded adapter is an execution-protocol smoke, not an OpenROAD QoR claim.
P5 replaces this admitted smoke surface with the pinned ORFS-Agent adapter.
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

Commands are `:new <natural-language goal>`, `:answer <clarification>`,
`:run [visible decision summary]`, `:cancel [reason]`, `:recover`,
`:refresh`, and `:quit`. It polls the cursor API and displays only returned
durable facts; it does not use a browser, local trace, or local state.

### A concrete teaching flow

With the real EDA tutorial profile above, try the following in the right-hand
**USER CLIENT** pane:

```text
Command> :new Implement the managed tutorial mux and retain QoR evidence.
```

The API creates a durable Session and records `goal_drafted`.  The current
teaching provider asks a real blocking typed confirmation about the fixed
operator profile:

```text
Client status: WAITING FOR CLARIFICATION
Question: Confirm baseline implementation of frozen mux_2to1 RTL on nangate45,
          clock period 10.0 ns. This will run the admitted local
          ORFS/OpenROAD toolchain.
```

The operator answers it through the same Session:

```text
Command> :answer Run one baseline RTL-to-GDS implementation and retain reports.
```

The left **L1 AGENT HARNESS** pane then receives and renders the stored facts:

```text
#  0 GOAL DRAFT
      clarification requested
#  1 FROZEN GOAL IR
      objective=Run one baseline RTL-to-GDS implementation and retain reports.
```

The operator explicitly requests the visible bounded decision:

```text
Command> :run Run the admitted ORFS baseline for frozen mux RTL at 10 ns.
```

It produces the following durable event categories, in order (identifiers and
timestamps vary):

```text
TYPED TOOL / PLAN       Run the admitted ORFS baseline for frozen mux RTL at 10 ns.
POLICY                  verdict=allow
RUNTIME RECEIPT         status=accepted; run_id=<runtime-id>
RUNTIME STATE           terminal_status=succeeded
```

For the `--backend orfs` profile, the final state is produced by real ORFS
stages (`synth → floorplan → place → cts → route → finish`) launched by
Runtime in an attempt-local workspace.  It retains the raw logs, GDS/DEF/ODB,
netlist, reports, metrics and content hashes.  This is a baseline EDA run, not
an L2 ORFS-Agent optimization campaign or a QoR-improvement claim.
