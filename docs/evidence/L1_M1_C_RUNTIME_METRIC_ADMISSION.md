# L1 M1-C Runtime metric admission

## Migration slice

- Boundary: admit the two native ORFS JSON reports needed by M1 as registered
  Runtime artifacts, and bind their derived execution metrics to those
  artifacts.  This is not evaluator logic and makes no QoR success claim.
- Changed files: `orfs_runner.py`, `orfs_adapter.py`, `runtime.py`, and the
  focused ORFS runner test.
- Before/after edge: ORFS metrics were labelled `ORFS finish JSON fallback`
  and had no source artifact id.  After the slice, adapter metric context
  carries only an internal registered store-key reference; Runtime resolves it
  after artifact registration to an artifact id, hash, parser id and version.
  L1/UI receives neither workspace nor store key.

## Real bounded smoke

On 2026-09-03, a new empty root was used:

```bash
PYTHONPATH=packages/contracts/src:packages/scheduler/src:packages/execution/src:. \
  .tools/venvs/orfs-agent/bin/python - <<'PY'
# WorkbenchService(..., backend="orfs") freezes the mux Goal and calls execute.
PY
```

Runtime run `f78fc673824d4f5f9f5eaac97fd6df91` succeeded with exit code `0`.
`runtime.sqlite` records these M1 facts:

| Metric | Value | Registered source | Parser |
| --- | ---: | --- | --- |
| `finish__timing__setup__ws` | `5.90111` | `.../6_report.json`, SHA `fe6c95ff...bea00` | `orfs-finish-report-json-v1@1` |
| `finish__design__instance__area` | `6.118` | same `6_report.json` artifact | `orfs-finish-report-json-v1@1` |
| `detailedroute__route__drc_errors` | `0` | `.../5_2_route.json`, SHA `246632ed...e1827` | `orfs-route-report-json-v1@1` |

The typed L1 `query_timing` and `query_drc` receipts both read that terminal
Runtime run and returned the corresponding bounded metric projection.  They
do not read report paths or raw logs.

## Focused verification

```bash
PYTHONPATH=packages/contracts/src:packages/scheduler/src:packages/execution/src:. \
  .tools/venvs/orfs-agent/bin/python -m pytest -q \
  tests/test_orfs_runner.py tests/test_orfs_plugin.py
```

Result: `21 passed`.

## Remaining M1-C work

This slice admits native metric names, not canonical Goal metric aliases.
The next M1-C slice must project them as `setup_wns_ns`, `area_um2`, and
`drc_errors` into DesignState while retaining the source metric and artifact
reference.  A missing report must remain `unknown`.

## Rollback

Revert this slice's commit.  It changes only artifact/metric provenance in the
Runtime result; it does not alter ORFS commands, RTL, SDC, PDK, evaluator,
toolchain, or the protected experiment protocol.
