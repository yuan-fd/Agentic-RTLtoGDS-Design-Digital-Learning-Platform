# Slice 037: evidence-backed convergence classification

## Boundary

This slice adds a dependency-free metric-trajectory contract and a
deterministic, direction-aware convergence classifier. It does not execute an
EDA task, choose parameters, trigger L2, perform rollback, or change a running
or completed campaign.

## Decision rule

Every point binds a Runtime run/attempt, metric, unit, stage, terminal status,
protocol hash, measurement authority and durable evidence. A trajectory rejects
mixed metrics, units or protocols. Failed points are retained and a failed
tail is `unknown`, never silently removed.

Positive signed benefit means improvement for both maximize and minimize
objectives. The classifier returns:

- `improving` only for a latest material improvement;
- `stalled` only when every transition in the configured tail is within the
  frozen absolute/relative tolerance;
- `diverging` only for consecutive material regressions; or
- `unknown` for insufficient, failed, mixed or inconclusive evidence.

This is an L1 control-plane assessment. It is not an optimizer.

## Changed files

- `packages/contracts/src/openroad_platform_contracts/convergence.py`
- `packages/contracts/src/openroad_platform_contracts/__init__.py`
- `packages/analysis/src/openroad_platform_analysis/convergence.py`
- `packages/analysis/src/openroad_platform_analysis/__init__.py`
- `tests/test_convergence.py`
- `scripts/run_convergence_acceptance.py`
- this record

## Tests and real bounded acceptance

Focused tests cover maximize/minimize direction, improving/stalled/diverging/
unknown results, failed-tail retention, protocol mismatch rejection, and
contract round trips.

The acceptance reads the completed historical full ORFS-Agent campaign in
SQLite read-only mode. It retains all 75 screening measurements, the four
protected successful optimizer observations, and three independent
confirmations. The mixed optimizer search is correctly left `unknown`; three
identical confirmation measurements are classified as stable (`stalled`); a
real failed tail remains `unknown`.

```text
var/evidence/evidence-backed-convergence-20260905-r1/summary.json
```

The exact SHA-256 and terminal acceptance status are written beside the
summary after execution. Stable confirmations prove repeated metric equality,
not optimizer convergence or PPA superiority.

## Protected and unrelated behavior

The source campaign and Runtime databases are SHA-pinned before and after the
acceptance. No Runtime, evaluator, RTL, PDK, SDC, protocol, plugin, product
surface, or old campaign state changes.

## Rollback

Remove the two convergence modules, their exports, focused test, acceptance
script and this record. Prior state contracts and evidence remain valid.
