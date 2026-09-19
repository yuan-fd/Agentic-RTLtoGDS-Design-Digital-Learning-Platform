# M1 RTL-to-GDS teaching module

This is the first independent teaching application. It owns only M1 teaching
state: frozen specs, RTL version metadata, verification status and v2 evidence
references. The raw RTL and all EDA outputs belong to the v2 execution service.

The module reaches v2 through `V2Client` over HTTP. It never imports v2 Runtime
code, opens a v2 database, executes a browser command, or substitutes a PDK or
previous result when a run is unavailable.

## Local checks

```bash
PYTHONPATH=packages/contracts/src:apps/m1_rtl_to_gds/src \
  python3 apps/m1_rtl_to_gds/smoke.py
python3 -m pytest -q tests/test_m1_service.py tests/test_m1_v2_client.py
```

The offline smoke proves state and submission gates only. It is not a GDS
claim. A real end-to-end acceptance must be recorded from the v2 HTTP service
with an admitted `orfs` Toolkit, a frozen `VerificationPackage`, and real
Nangate45 artifacts.
