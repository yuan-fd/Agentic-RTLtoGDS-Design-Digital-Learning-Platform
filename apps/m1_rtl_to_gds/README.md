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

## Local HTTP boundary

The module can serve its own static workbench and M1 API. It requires a running
v2 HTTP service; the browser never receives the v2 token and never executes an
EDA command.

```bash
PYTHONPATH=packages/contracts/src:apps/m1_rtl_to_gds/src \
  python3 -m openroad_app_m1 --serve --database .local/m1.sqlite \
  --v2-url http://127.0.0.1:8700
```

The API is intentionally small:

- `GET /api/m1/health`
- `POST /api/m1/specs`
- `POST /api/m1/specs/{spec_id}/freeze`
- `POST /api/m1/specs/{spec_id}/rtl`
- `POST /api/m1/rtl/{version_id}/verify`
- `POST /api/m1/rtl/{version_id}/simulate`
- `POST /api/m1/rtl/{version_id}/gds`
- `GET /api/m1/runs/{run_id}`

All mutating requests derive the owner from the v2 session. `SpecIR` and
`VerificationPackage` payloads remain versioned contracts; a missing or
incomplete specification produces a validation response and no v2 task.

For private acceptance, start v2 on `127.0.0.1:8700`, then run:

```bash
OPENROAD_V2_URL=http://127.0.0.1:8700 \
  bash scripts/start_teaching_platform.sh
```

The M1 UI listens on `127.0.0.1:8101`. Keep both services private and use an
SSH tunnel for browser acceptance.

The offline smoke proves state and submission gates only. It is not a GDS
claim. A real end-to-end acceptance must be recorded from the v2 HTTP service
with an admitted `orfs` Toolkit, a frozen `VerificationPackage`, and real
Nangate45 artifacts.
