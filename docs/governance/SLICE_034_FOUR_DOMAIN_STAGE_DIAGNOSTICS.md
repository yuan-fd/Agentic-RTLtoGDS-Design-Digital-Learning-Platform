# Slice 034: four-domain deterministic StageAnalysis

## Boundary

This slice defines dependency-free `StageAnalysis` and `DiagnosisReport`
contracts, then implements deterministic timing, congestion, DRC, and power
analysis over one authoritative Runtime describe view. It does not add a
Planner state machine, parse arbitrary paths, call an LLM, execute EDA, or
choose optimization parameters.

## Before / after dependency edge

Before:

```text
Runtime metrics/artifacts -> small query projections or legacy report rules
```

After:

```text
Runtime registered metric + source artifact
  -> canonical MetricFact
  -> four StageAnalysis records
  -> evidenced Headroom or explicit unknown
  -> DiagnosisReport with blockers, hypotheses, counter-evidence, next checks
```

Protected-evaluator canonical QoR outranks duplicate adapter metrics. An
adapter metric enters analysis only with parser identity and a registered
source artifact. Targets are never implicit: every threshold carries evidence.

## Contract semantics

- `MetricFact` is observed and carries authority, parser identity, unit, and
  evidence.
- `Headroom` has fixed operator semantics and validates its own numeric margin.
- `StageAnalysis` is `complete`, `partial`, or `unavailable`; missing data is
  never converted to zero.
- `DiagnosticStatement` is explicitly `unconfirmed` or `counter_evidence` and
  requires basis fact IDs, citations, and a falsification/verification check.
- `DiagnosisReport` requires exactly timing, congestion, DRC, and power.

The only initial cross-domain hypotheses are conservative correlations:
measured congestion plus measured timing/DRC failure may warrant a localized
correlation check. Clean global overflow is counter-evidence, not proof that
localized congestion is absent.

## Changed files

- `packages/contracts/src/openroad_platform_contracts/diagnostics.py`
- `packages/contracts/src/openroad_platform_contracts/__init__.py`
- `packages/analysis/src/openroad_platform_analysis/stage_diagnostics.py`
- `packages/analysis/src/openroad_platform_analysis/__init__.py`
- `tests/test_stage_diagnostics.py`
- `scripts/run_stage_diagnostics_acceptance.py`
- this record

## Focused tests

The focused suite passes and covers contract round trips, protected-evaluator
precedence, all four domains, exact headroom semantics, explicit missing-data
handling, unconfirmed hypotheses, counter-evidence, and rejection of metrics
without a parser-backed registered artifact.

## Real bounded acceptance

Input is the previously accepted real RTLScout Spec-to-GDS Runtime evidence:

```text
var/evidence/rtlscout-native-spec-to-gds-20260905-r8/summary.json
SHA-256 602a13dc56145ab3b3e3f7c290b92c269fe4f137b54e6e14b3185f8b075f4cb0
```

Canonical result:

```text
var/evidence/four-domain-stage-diagnostics-20260905-r1/summary.json
SHA-256 4677856456a0911471f8139f7a5d174c90a3052c3be56679bd01d0b2205ec98e
accepted true
```

Observed protected facts are setup WNS `5.65128 ns`, DRC `0`, and power
`8.214e-06 W`. Timing and DRC meet the cited protected-evaluator v3 rules.
Power has no supplied budget, so its headroom is unknown. No registered
congestion metric exists, so congestion is `unavailable`, not zero. The report
makes no root-cause hypothesis for this clean run.

This proves deterministic analysis and evidence continuity for one real run;
it does not prove broad root-cause localization or benchmark accuracy.

## Protected and unrelated behavior

No Runtime record, RTL, PDK, SDC, toolchain, evaluator, plugin, campaign, or
upstream source changed. Analysis reads the stored view and produces derived
contracts. The protected evaluator source hash is cited as the threshold-rule
source; it was not modified.

## Rollback

Remove `diagnostics.py`, `stage_diagnostics.py`, their exports, test,
acceptance script, and this record. Existing Runtime records and all prior
acceptance evidence remain unchanged.
