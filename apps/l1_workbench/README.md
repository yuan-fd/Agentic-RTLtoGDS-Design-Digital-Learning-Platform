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

Commands are `:new <natural-language goal>`, `:answer <clarification>`,
`:run [visible decision summary]`, `:cancel [reason]`, `:recover`,
`:refresh`, and `:quit`. It polls the cursor API and displays only returned
durable facts; it does not use a browser, local trace, or local state.
