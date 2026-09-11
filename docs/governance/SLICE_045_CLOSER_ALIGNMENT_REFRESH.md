# Slice 045: CLOSER paper alignment refresh after executed recovery

## Boundary

This analysis-only slice adds the accepted platform-owned cross-stage recovery
summary as a third immutable input to the existing public-paper alignment
audit. It does not change the Red CLOSER-Bench intake, register a plugin, run an
official task/scorer, or alter any EDA capability.

## Before / after dependency edge

Before:

```text
Spec-to-GDS evidence + typed recovery proposal -> 4 met / 2 partial / 4 missing
```

After:

```text
Spec-to-GDS evidence + typed recovery proposal + executed internal recovery
  -> 5 met / 2 partial / 3 missing
```

Only `executed_cross_stage_recovery_and_rollback_precision` changes from
missing to met. Its note explicitly says that the evidence is platform-owned
and not an official CLOSER task or oracle result.

## Changed files

- `packages/analysis/src/openroad_platform_analysis/closer_alignment.py`
- `tests/test_closer_alignment.py`
- `scripts/run_closer_protocol_alignment_audit.py`
- this record

## Tests and bounded evidence

Focused alignment/recovery tests: `6 passed`.

Canonical refreshed audit:

```text
var/evidence/closer-protocol-alignment-20260905-r2/summary.json
SHA-256 f3acd9b1f40fa4a9c1311f90495a207269c431b62f25b8a59b9335d019e8873b
```

Three criteria remain missing: official matched A/B/C stage pairs, released
shared hidden conditions/pristine oracle, and repeated-trial invalid-run and
confidence reporting. Consequently `official_closer_bench_result=false` and
`ready_for_official_benchmark_claim=false` remain unchanged.

## Protected and unrelated behavior

No external source, RTL, PDK, SDC, evaluator, Runtime execution, product route,
A2-ORFO policy or ORFS-Agent parameter domain changed. All three audit inputs
are verified by fixed SHA-256 before analysis.

## Rollback

Remove the optional executed-recovery input and its focused tests from the
alignment module/script. Preserve the r1 and r2 alignment summaries and the
Red intake record as historical evidence.
