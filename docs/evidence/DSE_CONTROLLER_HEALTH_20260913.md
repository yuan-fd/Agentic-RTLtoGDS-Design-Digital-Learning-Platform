# DSE controller health evidence — 2026-09-13

The controller worker was started with the same runtime database directory used by the API and an explicit heartbeat path:

```text
python3 scripts/run_dse_controller_worker.py \
  --runtime-db var/public/runtime.db \
  --optimization-db var/public/optimization.db \
  --heartbeat var/public/dse-controller.heartbeat.json
```

The API health response then reported:

```text
dse_controller_ready: true
dse_controller_status: idle
dse_controller_last_seen: <fresh heartbeat>
parameter_calibration_ready: true
```

The earlier `offline` result was a path mismatch: the worker's default heartbeat was under `/tmp/openroad-platform-<uid>`, while the API was reading beside `var/public/runtime.db`. No health flag was faked and no controller code was changed.
