#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT:$ROOT/packages/contracts/src:$ROOT/packages/execution/src:$ROOT/packages/scheduler/src:$ROOT/packages/analysis/src:$ROOT/packages/visualization/src${PYTHONPATH:+:$PYTHONPATH}"
export ORFS_ROOT="${ORFS_ROOT:-$ROOT/../OpenROAD-flow-scripts}"
export OPENROAD_BIN="${OPENROAD_BIN:-$ROOT/../bin/openroad}"
export YOSYS_BIN="${YOSYS_BIN:-$ROOT/../bin/yosys}"
export VERILATOR_BIN="${VERILATOR_BIN:-$(command -v verilator || true)}"
export IVERILOG_BIN="${IVERILOG_BIN:-$(command -v iverilog || true)}"

python3 "$ROOT/scripts/teaching_platform_doctor.py"
WORKER_COUNT="${WORKER_COUNT:-4}"
if ! [[ "$WORKER_COUNT" =~ ^[1-9][0-9]*$ ]] || (( WORKER_COUNT > 16 )); then
  echo "WORKER_COUNT must be an integer from 1 to 16" >&2
  exit 2
fi
worker_pids=()
for slot in $(seq 1 "$WORKER_COUNT"); do
  python3 "$ROOT/scripts/run_runtime_worker.py" --db "${PLATFORM_DB:-$ROOT/var/platform.db}" \
    --orfs-root "$ORFS_ROOT" --worker-slot "$slot" &
  worker_pids+=("$!")
done
cleanup() {
  for pid in "${worker_pids[@]}"; do kill "$pid" 2>/dev/null || true; done
  for pid in "${worker_pids[@]}"; do wait "$pid" 2>/dev/null || true; done
}
trap cleanup EXIT INT TERM
python3 "$ROOT/apps/api/app.py" --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}" \
  --db "${PLATFORM_DB:-$ROOT/var/platform.db}" --orfs-root "$ORFS_ROOT"
