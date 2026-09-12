# Platform regression (2026-09-12)

Command:

```text
python3 -m pytest -q
```

Result:

```text
857 passed, 1 deselected, 63 warnings in 448.77s
```

The run covered the Runtime, contracts, optimizer/controller, API, teaching
modes, campaign read models, RTL comparison, and web clarity tests. Warnings
were dependency deprecation/numerical warnings from Ray, Optuna, and BoTorch;
no test failed.
