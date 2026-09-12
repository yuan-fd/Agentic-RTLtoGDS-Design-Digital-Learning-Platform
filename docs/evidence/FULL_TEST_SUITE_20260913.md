# Full test suite evidence — 2026-09-13

## Command

```text
python3 -m pytest -q
```

## Result

```text
858 passed, 1 deselected, 63 warnings in 404.45s (0:06:44)
```

The warnings come from optional Ray, Optuna, BoTorch, and GPyTorch integrations. No test failed.

This is repository-wide regression evidence. It does not by itself prove that a fresh OpenROAD run, browser workflow, or multi-user load test has been completed; those remain separate acceptance checks.
