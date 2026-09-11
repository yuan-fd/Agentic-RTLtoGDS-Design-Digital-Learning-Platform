# Slice 042: PostEDA-Bench bounded diagnostic evaluation

## Boundary

This slice evaluates one existing deterministic L1 DRC analysis and typed
decision against one pinned PostEDA-Bench task. It does not add an optimizer,
repair action, reference agent, full benchmark harness, PPA flow, or product
route.

```text
public prompt + precomputed DRC report
  -> Runtime public-case capability
  -> four-domain DiagnosisReport + sealed typed decision
  -> Runtime scorer-only capability
  -> derived diagnostic score
```

The public capability cannot receive or read `info.json`. The prediction
contract requires `hidden_label_accessed=false`. Only after the prediction is
persisted does the scoring capability read the hidden task metadata. Hidden
values are not copied into scorer output.

## Before / after dependency edge

Before:

```text
StageAnalysis/DiagnosisReport -> local acceptance assertions only
```

After:

```text
StageAnalysis/DiagnosisReport
  -> typed PostEDADiagnosisPrediction
  -> isolated external-benchmark scorer
  -> artifact-backed PostEDADiagnosisScore
```

Contracts remain dependency-free. Analysis imports contracts; execution owns
the adapter and TaskSpec mapping; Runtime remains the process/artifact
authority. The benchmark plugin is not added to `DEFAULT_PRODUCT_SURFACE`.

## External intake and native smoke

Canonical upstream, exact commit/tree, CC BY 4.0 conclusion, native
entrypoints, dependencies, security review and adapter boundary are recorded
in `docs/governance/POSTEDA_BENCH_INTAKE.md` and
`integrations/posteda_bench/source.lock.json`.

The required native-before-platform smoke passed:

```text
var/evidence/posteda-native-diagnostic-20260905-r1/summary.json
SHA-256 daa938e6d951918b891704025b0eabe9cc70222e6de1fcf58a608fcd3df9b365
```

It uses the upstream `drc_error_collection.py` through KLayout 0.30.6 in an
isolated workspace and parses one public `WELL.W.1` marker. It is not an agent
or repair result.

## Changed files

- `packages/contracts/src/openroad_platform_contracts/benchmark_evaluation.py`
- `packages/contracts/src/openroad_platform_contracts/__init__.py`
- `packages/analysis/src/openroad_platform_analysis/posteda_bench.py`
- `packages/analysis/src/openroad_platform_analysis/__init__.py`
- `packages/execution/src/openroad_platform_execution/posteda_bench_plugin.py`
- `packages/execution/src/openroad_platform_execution/__init__.py`
- `integrations/posteda_bench/source.lock.json`
- `integrations/posteda_bench/posteda-bench.plugin.json`
- `integrations/posteda_bench/posteda_bench_adapter.py`
- `integrations/posteda_bench/posteda_bench_launcher.py`
- `tests/test_posteda_bench.py`
- `scripts/run_posteda_native_diagnostic_smoke.py`
- `scripts/run_posteda_platform_diagnostic_acceptance.py`
- this record and intake/status documentation

## Tests and real bounded acceptance

Focused tests: `5 passed`. They cover contract round trips, public/private
TaskSpec separation, hidden-field and shell-field rejection, four-domain
mapping, typed decision and plugin discovery.

Canonical platform result:

```text
var/evidence/posteda-platform-diagnostic-20260905-r1/summary.json
SHA-256 1684cbea302c22100ad08bfa0efe50a283b42fe758d617c44281c299b1d04a3b
```

Two real Runtime processes succeeded. The first produced the public case from
the pinned native KLayout parser. L1 recorded `drc_errors=1`, headroom `-1`,
the blocker `drc_errors_target_violated`, and a typed
`inspect_drc_geometry` decision with Runtime artifact evidence. The sealed
prediction then received a derived score of 1.0 for exact type count, exact
total, evidence presence and the safe decision class.

This is a one-task integration result. The score is deliberately
`official_metric=false`: it is not PostEDA-Bench SR, ERR or VRR, does not show
that a DRC was repaired, and is not evidence of broad diagnosis accuracy.

## Protected and unrelated behavior

No PostEDA source, task, GDS, hidden label, platform RTL/PDK/SDC, evaluator,
ORFS/A2 campaign or product role was modified. The checkout is clean before
and after evaluation. No Docker, model provider, network call or PPA flow ran.

## Rollback

Remove the PostEDA contracts, analysis adapter, plugin registration, tests and
scripts listed above. Preserve the intake, source lock and all native/Runtime
evidence. The ignored pinned checkout may be removed only after proving no
retained evidence references it.
