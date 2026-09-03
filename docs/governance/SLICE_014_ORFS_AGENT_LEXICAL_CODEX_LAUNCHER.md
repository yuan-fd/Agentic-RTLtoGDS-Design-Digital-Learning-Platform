# Slice 014 — ORFS-Agent lexical Codex launcher boundary

Date: 2026-09-01

## Purpose

Resolve the stopped Slice 013 environment boundary without changing an
optimizer, OpenROAD flow, evaluator, benchmark, PDK, objective, budget, or
search domain. This slice applies only to the child environment used by the
platform-managed policy invocation before the pinned ORFS-Agent GP/EI call.

## Before and after

Before, the Manifest verified `~/.nvm/.../bin/codex` by resolving its symlink
and then stored the resolved JavaScript target as `ORFS_AGENT_CODEX_EXECUTABLE`.
The Adapter consequently had no reliable way to find NVM's sibling `bin/node`
when executed under the deliberate systemd minimal PATH.

After:

1. Manifest admission validates the resolved target but stores the original,
   absolute launcher path; and
2. the Adapter preserves that lexical launcher directory and prepends it only
   to the one Codex child process when it contains an executable sibling
   `node`.

No shell startup file is sourced and no global or systemd PATH is changed.

## Focused verification

`tests/test_orfs_agent_plugin.py` now constructs an NVM-style symlinked
`codex` launcher with a sibling `node` and executes the native ORFS-Agent
path with `PATH=/usr/bin:/bin`. The test reaches the pinned upstream GP/EI
path and passed.

The complete focused suite passed:

```text
23 passed in 17.34s
tests/test_orfs_agent_plugin.py
tests/test_external_l2_service.py
tests/test_process_guardian.py
tests/test_orfs_agent_equal_budget_aggregation.py
```

The real acceptance smoke is retained at:

`var/orfs-agent-manifest-policy-smoke-20260901-lZEQ8q`.

It used the original 19 feasible v5 Runtime observations but a separate
workspace, the same minimal PATH as user-systemd, and the actual Manifest and
`ProcessAdapter`. It succeeded with:

* adapter: `orfs-agent-native-policy-plus-upstream-gp-ei`;
* admitted source commit: `730f1fa11f9c17c0aaac332412af2b2538f42e9b`;
* candidate algorithm: `scikit-optimize GP + EI`;
* fixed optimizer seed: `20260830`; and
* 50 emitted candidates.

It did not launch OpenROAD or create a PPA claim.

## Rollback

Revert the two implementation/test changes in this slice. The smoke and v5
failure artifacts remain evidence and must not be deleted. A fresh formal
campaign is required in either case; v5 is not resumable or comparable.
