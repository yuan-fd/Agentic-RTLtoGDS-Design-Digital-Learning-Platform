# Slice 004: target-domain timeout alignment

Status: accepted before the formal ORFS-Agent campaign starts.

## Problem and evidence

The three-replica target-domain preflight is run with a 3600-second per-stage
limit.  The formal campaign previously defaulted to 2700 seconds.  A parameter
could therefore be admitted as feasible in the preflight and then be marked as
a formal-campaign failure solely because the formal resource policy was more
strict.  That would confound a resource-policy difference with GP/EI quality.

The active preflight uses `--stage-timeout 3600`; its immutable receipt is at
`var/orfs-agent-target-feasibility-20260831-sky130hd-aes-v4-verified-anchor/`
and records that policy.  The formal output directory does not yet exist, so
no measurement, evaluator result, or claimed comparison was changed.

## Intent and boundary

Only the formal campaign's default per-stage timeout is aligned to the frozen
preflight value.  This is not an optimisation, a retry, or a relaxation of a
failure after the fact.  It makes the two explicitly connected protocol phases
use one declared resource policy before the second phase begins.

## Changed files

| File | Change |
| --- | --- |
| `scripts/run_orfs_agent_paper_campaign.py` | Added a named `FORMAL_STAGE_TIMEOUT_SECONDS = 3600` contract and made the CLI parser expose it. |
| `tests/test_orfs_agent_plugin.py` | Added a parser-level regression test for the formal/preflight timeout invariant. |
| `docs/governance/ORFS_AGENT_PAPER_COMPARABLE_PROTOCOL.md` | Records the common 3600-second stage limit in the frozen protocol. |

## Verification

The following command passed after the change:

```text
python3 -m pytest -q \
  tests/test_orfs_agent_plugin.py \
  tests/test_external_l2_service.py \
  tests/test_target_feasibility.py \
  tests/test_package_architecture_boundaries.py

19 passed in 22.38s
```

`python3 -m py_compile scripts/run_orfs_agent_paper_campaign.py` and
`git diff --check` also passed.  The regression test parses the actual formal
campaign CLI and asserts its default is exactly 3600 seconds.

## Protected-component and rollback check

No upstream source, adapter algorithm, benchmark RTL, SDC, PDK, toolchain,
evaluator, seed, search space, statistics rule, current preflight task, or
historical artifact changed.  The running preflight remains untouched.  If a
rollback is required before the formal campaign starts, revert this slice's
three source/documentation changes; do not delete the preflight evidence.
