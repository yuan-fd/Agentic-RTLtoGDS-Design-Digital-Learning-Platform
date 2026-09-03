# L1 S7 terminal Harness acceptance

## Migration slice

- Boundary: replace the workbench's teaching surface with a terminal-only,
  two-sided projection over the durable L1 HTTP API.
- Changed files: `apps/l1_workbench/terminal_dashboard.py`,
  `apps/l1_workbench/README.md`, and
  `tests/test_l1_terminal_workbench_contract.py`.
- Dependency edge: terminal client → L1 HTTP API → durable Session/trace/
  Policy/Runtime.  There is no terminal-client import of Runtime, plugin,
  SQLite trace, optimizer, or EDA process.

## Acceptance

Focused checks on 2026-09-03:

```bash
PYTHONPATH=packages/contracts/src:packages/scheduler/src:packages/execution/src:. \
  .tools/venvs/orfs-agent/bin/python -m pytest -q \
  tests/test_l1_tutorial_planner.py tests/test_l1_workbench_api.py \
  tests/test_l1_tutorial_profile.py tests/test_l1_runtime_bridge.py \
  tests/test_l1_terminal_workbench_contract.py
```

Result: `20 passed`.

A live API smoke also drove the terminal client's command methods against a
fresh `--backend smoke` server: create Session → typed answer → frozen Goal →
typed `run_full_flow` → Policy `ALLOW` → Runtime exit `succeeded` → cursor
event read.  This validates the terminal transport and projections only.  The
real EDA evidence is separately recorded in
`L1_S6_REAL_ORFS_TUTORIAL_ACCEPTANCE.md`; the terminal does not manufacture or
replace it.

The visible layout is intentionally teaching-oriented:

```text
left Harness:  1 Goal / IR | 2 Tool / Policy
               3 State / Evidence | 4 Reflection / Replay
right Client:  natural-language request, required typed answers, controls
```

The Harness shows stored decision summaries and evidence references, not a
provider transcript or hidden chain-of-thought.  `:advance`, `:query`,
`:artifact`, and `:stage` all call API routes; none can issue shell text or
own Session state.

## Rollback

Revert the terminal-Harness commit.  This removes only the presentation and
its documentation/test; durable contracts, Runtime, plugins, old Web
dashboard, RTL, PDK, SDC, evaluator, and toolchain remain unchanged.
