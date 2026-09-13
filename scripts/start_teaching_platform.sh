#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT:$ROOT/packages/contracts/src:$ROOT/packages/execution/src:$ROOT/packages/scheduler/src:$ROOT/packages/analysis/src:$ROOT/packages/visualization/src${PYTHONPATH:+:$PYTHONPATH}"
export ORFS_ROOT="${ORFS_ROOT:-$ROOT/../OpenROAD-flow-scripts}"
export OPENROAD_PLATFORM_NO_AUTH="${OPENROAD_PLATFORM_NO_AUTH:-1}"
export OPENROAD_BIN="${OPENROAD_BIN:-$ROOT/../bin/openroad}"
export YOSYS_BIN="${YOSYS_BIN:-$ROOT/../bin/yosys}"
export VERILATOR_BIN="${VERILATOR_BIN:-$(command -v verilator || true)}"
export IVERILOG_BIN="${IVERILOG_BIN:-$(command -v iverilog || true)}"
RUNTIME_DB="${RUNTIME_DB:-$ROOT/var/public/runtime.db}"
OPTIMIZATION_DB="${OPTIMIZATION_DB:-$ROOT/var/public/optimization.db}"

python3 "$ROOT/scripts/teaching_platform_doctor.py"
PLATFORM_DB="${PLATFORM_DB:-$ROOT/var/platform.db}" \
  python3 -c 'from openroad_platform_scheduler import JobStore; import os; JobStore(os.environ["PLATFORM_DB"])'
WORKER_COUNT="${WORKER_COUNT:-4}"
if ! [[ "$WORKER_COUNT" =~ ^[1-9][0-9]*$ ]] || (( WORKER_COUNT > 16 )); then
  echo "WORKER_COUNT must be an integer from 1 to 16" >&2
  exit 2
fi
worker_pids=()
for slot in $(seq 1 "$WORKER_COUNT"); do
  python3 "$ROOT/scripts/run_runtime_worker.py" --db "${PLATFORM_DB:-$ROOT/var/platform.db}" \
    --orfs-root "$ORFS_ROOT" --runtime-db "$RUNTIME_DB" --worker-slot "$slot" &
  worker_pids+=("$!")
done
python3 "$ROOT/scripts/run_dse_controller_worker.py" --db "${PLATFORM_DB:-$ROOT/var/platform.db}" \
  --orfs-root "$ORFS_ROOT" --runtime-db "$RUNTIME_DB" --optimization-db "$OPTIMIZATION_DB" &
worker_pids+=("$!")
cleanup() {
  for pid in "${worker_pids[@]}"; do kill "$pid" 2>/dev/null || true; done
  for pid in "${worker_pids[@]}"; do wait "$pid" 2>/dev/null || true; done
}
trap cleanup EXIT INT TERM
python3 "$ROOT/apps/api/app.py" --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}" \
  --db "${PLATFORM_DB:-$ROOT/var/platform.db}" --orfs-root "$ORFS_ROOT" \
  --runtime-db "$RUNTIME_DB" --optimization-db "$OPTIMIZATION_DB"
