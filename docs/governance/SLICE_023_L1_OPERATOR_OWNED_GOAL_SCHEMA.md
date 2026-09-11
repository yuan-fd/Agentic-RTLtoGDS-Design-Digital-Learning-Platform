# Slice 023 — operator-owned L1 GoalDraft schema

## Intended architectural change

Move clarification-question ownership out of the untrusted language provider.
The L1 composition root supplies a typed, reviewed question schema before a
Codex or deterministic provider is called. The provider may copy that schema
and attach typed answers inferred from the user's request, but may not create,
delete, rename, re-field, reword, reorder, or weaken questions.

This slice changes only the natural-language-to-`GoalDraft` boundary. It does
not change Runtime, EDA parameters, protected evaluation, the L2 domain, the
upstream ORFS-Agent optimizer, or campaign budgets.

## Changed file boundary

- `packages/scheduler/src/openroad_platform_scheduler/l1_model_boundary.py`
- `packages/scheduler/src/openroad_platform_scheduler/l1_session_service.py`
- `apps/l1_workbench/codex_goal_provider.py`
- `apps/l1_workbench/tutorial_profile.py`
- `apps/l1_workbench/tutorial_semantic.py`
- `apps/l1_workbench/service.py`
- `scripts/run_l1_codex_goal_schema_smoke.py`
- `tests/test_l1_model_boundary.py`
- `tests/test_l1_session_service.py`
- `tests/test_l1_codex_goal_provider.py`
- `tests/test_l1_codex_tool_loop.py`
- `tests/test_l1_tutorial_semantic.py`
- `tests/test_l1_tutorial_profile.py`
- `tests/test_l1_workbench_api.py`
- `tests/test_l1_workbench_evaluator.py`
- this evidence record

## Before and after dependency edge

Before: a provider receives only free text and can invent question ids,
fields, prompts, and blocking flags. Profile compilation may reject bad answer
values later, but the conversation protocol itself is model-owned and Codex
question ids can be incompatible with profile ids.

After: the application asks the operator profile for
`ClarificationQuestion` values and the scheduler serializes them into the
provider request. `L1ModelBoundary` requires exact structural equality on the
initial response. Revision handling requires equality with the complete prior
question tuple, including prompt and order. No provider output authorizes a
tool; `GoalFinalizer`, Policy, and Runtime retain their existing authority.

## Acceptance evidence

Focused boundary and vertical-slice suite:

```text
34 passed in 6.18s
```

Command:

```text
python3 -m pytest -q \
  tests/test_l1_model_boundary.py \
  tests/test_l1_session_service.py \
  tests/test_l1_codex_goal_provider.py \
  tests/test_l1_codex_tool_loop.py \
  tests/test_l1_tutorial_semantic.py \
  tests/test_l1_tutorial_profile.py \
  tests/test_l1_workbench_api.py \
  tests/test_l1_workbench_evaluator.py
```

Real managed-login structured smoke:

- evidence directory:
  `var/evidence/l1-codex-goal-schema-20260904-r1`
- summary SHA-256:
  `df0c00e00aed260a6504844354918050bd73ccb1f730f062fe587e4e7d100153`
- provider: `codex-cli-l1-goal-v1`
- model: `gpt-5.6-terra`
- CLI: `codex-cli 0.147.0`
- invocation: ephemeral, read-only sandbox, no fallback
- result: `clarification_required`
- expected and returned question-schema SHA-256:
  `cdaa3e47b081dc654777df663978a5ccf2ad8dbbf5a0f946c2a900ac0e7c038b`
- exact schema match: `true`
- Runtime runs created: `0`

The six blocking questions cover objective, constraints, protected clock/SDC,
change scope, EDA-run budget, and the exact managed AES/Sky130HD 4.5 ns design
context. The request intentionally supplied none of the controlled values, so
the real model correctly returned no answers and the session could not
finalize or execute.

The smoke proves only the real language-provider boundary and durable
clarification state. It is not physical-design, QoR, or L2 campaign evidence.

## Protected components and unrelated behavior

No RTL, SDC, PDK, evaluator, ORFS checkout, toolchain, or optimizer input is
changed. No API key field is introduced; the Codex CLI uses its managed login
state and an ephemeral read-only invocation.

The default test Workbench now also owns its historical `objective-1`
question explicitly. Its deterministic provider only copies the supplied
schema. This preserves the API behavior without restoring provider authority.

## Rollback

Revert only the files listed above and remove the new smoke evidence directory.
A rollback restores the earlier provider-owned question behavior and therefore
must not be described as retaining this security boundary. No Runtime data,
EDA workspace, protected input, or external checkout needs restoration.
