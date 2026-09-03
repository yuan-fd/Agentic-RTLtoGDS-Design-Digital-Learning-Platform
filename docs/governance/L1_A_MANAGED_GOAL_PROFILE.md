# L1-A: managed tutorial Goal profile

Status: accepted implementation slice (2026-09-03)

## Intent

Replace the Workbench's former single confirmation with a bounded, typed
tutorial conversation whose answers compile into a frozen `DesignGoal`.
This is a Goal/Session boundary only: it does not change ORFS execution,
Runtime, evaluator, RTL, SDC, PDK, or the legacy dashboard.

## Dependency edge

```text
before: GoalDraft answers -> fixed policy Goal (answers were display-only)
after:  GoalDraft typed answers -> managed profile compiler -> frozen Goal IR
```

The compiler receives only `GoalDraft` and `TrustedGoalPolicy`; it has no
Runtime, path, shell, tool-process, or plugin access.

## Operator-owned profile

For the managed `mux_2to1/nangate45` tutorial, users must answer:

- objective: `timing`, `balanced`, `area`, or `power`;
- constraints: `drc_zero_area_plus_3pct`;
- protected clock/SDC: `protect_clock_sdc`;
- change scope: `registered_parameters_only`; and
- EDA budget: `1`, `2`, or `3`.

The resulting Goal records WNS >= 0, DRC = 0, area/baseline <= 1.03,
protected scope, selected preference, and the selected bounded run budget.
Design, RTL hash, platform, toolchain, allowed parameters, and the maximum
budget remain profile/policy facts rather than browser or model authority.

## Changed files

- `packages/scheduler/.../l1_session_service.py`
- `apps/l1_workbench/tutorial_profile.py`
- `apps/l1_workbench/service.py`
- `apps/l1_workbench/terminal_dashboard.py`
- `tests/test_l1_tutorial_profile.py`

## Acceptance evidence

Focused command:

```text
pytest -q tests/test_l1_tutorial_profile.py tests/test_l1_workbench_api.py
tests/test_l1_session_service.py tests/test_l1_goal_finalizer.py
tests/test_l1_runtime_bridge.py tests/test_l1_durable_loop.py
```

Result: `31 passed`.

The staged profile preflight answered the five questions one at a time.  The
Session remained `clarification_required` until the fifth answer; it then
became `goal_finalized`, with both frozen Goal and initial `DesignState`
recording the requested `2` EDA-run budget.

## Rollback

Revert this slice's commit.  Session records created under this profile remain
historical audit evidence; do not delete them.  No database schema migration,
toolchain modification, or protected-input change is required.
