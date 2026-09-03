# L1-C: evidence-backed tutorial planner and safe stop

Status: accepted implementation slice (2026-09-03)

## Boundary

Add a deterministic, inspectable teaching planner above the existing typed
tools.  It has no access to an EDA process, adapter command, workspace path,
optimizer, evaluator, shell, or arbitrary user action.  It only selects a
fixed typed next action from durable Goal/State/trace facts.

```text
Goal + DesignState + trace evidence
  -> visible TutorialDecision
  -> existing Policy / Runtime path or durable reflection
```

The sequence is `baseline → timing query → continue reflection → route stage
→ DRC query → stop reflection`.  Missing canonical DRC evidence is explicitly
classified as `missing_drc_evidence`; it is never silently treated as DRC=0.

## Changed files

- `apps/l1_workbench/tutorial_planner.py`
- `apps/l1_workbench/service.py`
- `apps/l1_workbench/server.py`
- `tests/test_l1_tutorial_planner.py`

## Acceptance evidence

Focused unit/API suite passed:

```text
19 passed
tests/test_l1_tutorial_planner.py
tests/test_l1_workbench_api.py
tests/test_l1_tutorial_profile.py
tests/test_l1_runtime_bridge.py
```

The real fully automatic run is retained at:

```text
/tmp/openroad-l1-c-real-20260903
```

It has one profile-frozen Goal, five persisted clarification answers, two
successful real ORFS Runtime runs, typed timing and DRC query receipts, and
two durable reflections.  Its trace sequence is:

```text
goal_finalized
→ run_full_flow / allow / receipt / state_transition
→ query_timing / allow / receipt
→ reflection(continue)
→ run_stage(route) / allow / receipt / state_transition
→ query_drc / allow / receipt
→ reflection(stop, missing_drc_evidence)
```

The state budget is `3 → 2 → 1`.  The final stop is a correctness result, not
a QoR success claim: this managed ORFS profile did not expose a canonical
`drc_errors` metric to the typed state.

## Rollback

Revert this slice commit.  Preserve both evidence roots and their durable
Runtime/trace stores.  No protected input, external source, Runtime adapter,
or evaluator migration is involved.
