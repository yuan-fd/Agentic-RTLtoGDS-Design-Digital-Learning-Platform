# Slice 028 — exact ORFS-Agent native execution mapping

## Problem

Every one of the first 30 terminal initial candidates failed before synthesis
with `File name too long`. Four attempts interrupted by the Runtime database
failure had already emitted the same raw log message. The adapter put unrounded
Python float strings into upstream's descriptive `FLOW_VARIANT` directory.

## Evidence

The pinned upstream entrypoint
`AutoTuner-integration/ORFS-with-AutoTuner/orfs_agent.py:run_or` rounds `CLK`,
`UTIL`, `LB_ADDON`, `PIN_ADJ`, and `UP_ADJ` to three decimal places before
calling `run_job`; discrete controls are cast to integers. The optimizer row is
then merged back into the observation unchanged. The platform adapter had
copied the `run_job` environment and job-name shape but omitted this preceding
mapping.

The r2 controller contains 50 unique candidates with exactly 12 fields and a
live CLK range of `0.5846181561607575..14.936437101506558`. Thus this was not a
reduced search domain. All 34 started workspaces retain their raw logs; all 34
contain `File name too long`.

## Why the current plan fails

Continuing r2 after changing execution mapping would combine two adapter
protocols in one frozen experiment. Truncating the path, rounding optimizer
rows in place, fixing the clock, or reducing dimensions would alter algorithm
inputs or provenance and violate the tutorial architecture.

## Options

- Option A: replace the upstream job name with a platform hash. This would fit
  but no longer reproduce the native launcher representation.
- Option B: reproduce upstream `run_or` exactly: retain the original 12-D row
  for GP/EI feedback and record a separate native execution candidate whose
  five continuous values are rounded to three decimals.

## Recommendation and implemented boundary

Option B is implemented in the bounded adapter. The receipt records both
`candidate` and `native_execution_candidate`, plus the upstream owner,
entrypoint, and mapping rule. All 12 dimensions remain live. This is restoration
of upstream semantics, not platform-side snapping or parameter freezing.

Changed files:

- `integrations/orfs_agent/orfs_agent_reproduction_adapter.py`
- `tests/test_orfs_agent_reproduction_adapter.py`
- `var/evidence/orfs-agent-native-rounding-smoke-20260904-r1-input.json`
- this record

Before: `optimizer 12-D row -> raw float strings -> upstream FLOW_VARIANT/make`.

After: `optimizer 12-D row (preserved) -> upstream run_or mapping -> bounded
FLOW_VARIANT/make -> metrics joined back to preserved row`.

Focused result together with Runtime durability tests:

```text
15 passed in 1.74s
```

The actual bounded tool smoke succeeded:

- evidence: `var/evidence/orfs-agent-native-rounding-smoke-20260904-r1`;
- Runtime run: `fb37caf09e854d36a31f85414029bf18`;
- summary SHA-256:
  `aba220df8d77661866d73bedcc025645bcf496f7dff4d8fe2e62fbb0fd8ccb5d`;
- 12 registered artifacts, with zero missing files or recomputed SHA mismatch;
- original values include `CLK=0.500000000000013`,
  `PIN_ADJ=0.100000000000017`, `UP_ADJ=0.100000000000019`, and
  `LB_ADDON=2.3e-14`; the separately recorded upstream execution values are
  `0.5`, `0.1`, `0.1`, and `0.0`;
- native variant length: 201 bytes; all 50 preserved r2 initial candidates
  preflight to 208–212 bytes after the same mapping, with zero over 255;
- Runtime terminal status `succeeded`; protected evaluation id
  `f959117dcd3754187d47a4cb30587deb7d53eb3c12197d3cab54b530c1ea4e6d`;
- protected evaluation remains honestly `feasible=false` because WNS is
  `-4.72413 ns`, the native tunereport boundary has no GDS, and the paper flow
  lacks a synth-stage JSON. The smoke proves execution compatibility, not QoR
  attainment or PPA superiority;
- Runtime database is `journal_mode=delete`, `quick_check=ok`; both external
  worktrees remained clean.

## Protected components

The adapter does not modify ORFS-Agent source, the paper ORFS checkout, RTL,
PDK, SDC, evaluator, search bounds, objective set, seeds, or the
`50 + 5*5 + 3 = 78` campaign budget. Both external worktrees must remain clean.

## Rollback

Revert the adapter/test/input/doc files. r2 remains immutable diagnostic
evidence and must not be resumed under either adapter revision.
