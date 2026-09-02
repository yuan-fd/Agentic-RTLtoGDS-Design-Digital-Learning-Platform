# L1-S1 semantic contracts and trusted goal finalization

Status: implementation slice, awaiting independent merge-gate re-review
Date: 2026-09-02

## Boundary

This slice establishes only dependency-free L1 contracts and deterministic
goal finalization. It does not execute OpenROAD, modify Runtime/evaluator,
register an external plugin, or change API/UI behavior.

## Changed files

- `packages/contracts/src/openroad_platform_contracts/agent_control.py`
- `packages/contracts/src/openroad_platform_contracts/l1_goal_draft.py`
- `packages/contracts/src/openroad_platform_contracts/l1_tool_contract.py`
- `packages/scheduler/src/openroad_platform_scheduler/l1_goal_finalizer.py`
- their focused tests.

## Before and after dependency edge

```text
Before: natural-language handling had no committed contract baseline.
After: GoalDraft -> verified policy finalizer -> DesignGoal; planner -> one
       tutorial ToolName -> policy/Runtime boundary.
```

`contracts` imports only contract-local modules and the Python standard
library. The finalizer reads an answered draft and a provenance-bearing,
operator-issued policy; it does not trust draft content for artifact, budget,
toolchain, parameter, or tool allowlists.

## Acceptance and evidence

- Tutorial registry contains exactly its fixed 12-tool surface, once each.
- Schema validation recursively rejects shell/command/path/environment and
  credential-like fields, including nested/compound names.
- `CLOCK_SDC_POLICY` remains a blocking clarification.
- Default `DesignGoal` tools exclude legacy/internal `create_experiment` and
  `propose_search_policy`.
- Final goals record draft digest and policy id/version/issuer/provenance.
- Focused command: `PYTHONPATH=packages/contracts/src:packages/scheduler/src
  .tools/venvs/orfs-agent/bin/python -m pytest -q
  tests/test_l1_agent_control_contract.py tests/test_l1_goal_draft_contracts.py
  tests/test_l1_tool_contracts.py tests/test_l1_goal_finalizer.py`.

No real tool smoke applies: this slice has no tool invocation.

## Protected components and rollback

Runtime, protected evaluator, benchmark assets, upstream source locks,
external plugins, historical data, API, and web UI are unchanged. No database
or artifact migration is present. Roll back with the following newest-first
commands (do not reset a dirty worktree):

```bash
git revert --no-edit f390891
git revert --no-edit 65b99df
git revert --no-edit 683d008
git revert --no-edit 264a544
git revert --no-edit c4c0729
git revert --no-edit 0daad7f
git revert --no-edit f6ce287
git revert --no-edit 3df763d
git revert --no-edit 2697f71
```

`5c3639f` and `6551e45` are L1-S2 trace commits and are intentionally outside
this S1 rollback sequence.
