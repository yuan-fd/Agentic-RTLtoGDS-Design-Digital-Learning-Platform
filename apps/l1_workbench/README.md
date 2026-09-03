# L1 Workbench vertical slice

This is the operational seed of the L1 Workbench, not the frozen trace
dashboard. It composes `L1SessionService`, `L1TraceService`,
`L1DurableLoop`, `L1RuntimeBridge`, and `WorkflowRuntime`; the HTTP handler
only transports requests and renders stored facts.

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

The following is a real sequence for the current vertical slice, suitable for
trying in the right-hand **USER CLIENT** pane:

```text
Command> :new I want to run a bounded implementation flow and retain auditable evidence.
```

The API creates a durable Session and records `goal_drafted`.  The current
deterministic teaching provider asks one real blocking typed question:

```text
Client status: WAITING FOR CLARIFICATION
Question: Confirm this bounded Runtime tool execution.
```

The operator answers it through the same Session:

```text
Command> :answer Complete one audited bounded flow.
```

The left **L1 AGENT HARNESS** pane then receives and renders the stored facts:

```text
#  0 GOAL DRAFT
      clarification requested
#  1 FROZEN GOAL IR
      objective=Complete one audited bounded flow.
```

The operator explicitly requests the visible bounded decision:

```text
Command> :run Execute one bounded typed Runtime tool.
```

It produces the following durable event categories, in order (identifiers and
timestamps vary):

```text
TYPED TOOL / PLAN       Execute one bounded typed Runtime tool.
POLICY                  verdict=allow
RUNTIME RECEIPT         status=succeeded; evidence=1
RUNTIME STATE           terminal_status=succeeded
```

For this teaching slice the final receipt records a real Runtime subprocess,
exit code `0`, and a content-addressed `report` artifact.  It is not yet a
claim that OpenROAD or ORFS-Agent ran; replacing this bounded smoke adapter
with a pinned, admitted external EDA adapter is a separate integration slice.
