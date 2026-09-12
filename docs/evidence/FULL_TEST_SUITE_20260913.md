# Full test suite evidence — 2026-09-13

## Command

```text
python3 -m pytest -q
```

## Result

```text
861 passed, 1 deselected, 63 warnings in 427.05s (0:07:07)
```

The warnings come from optional Ray, Optuna, BoTorch, and GPyTorch integrations. No test failed.

This is repository-wide regression evidence after the SQLite startup-lock fix and mutation operator update. It does not by itself prove that a fresh OpenROAD run, browser workflow, or multi-user load test has been completed; those remain separate acceptance checks.
