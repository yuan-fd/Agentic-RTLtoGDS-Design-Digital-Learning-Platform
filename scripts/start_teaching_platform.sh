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
exec python3 "$ROOT/apps/api/app.py" --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}" \
  --db "${PLATFORM_DB:-$ROOT/var/platform.db}" --orfs-root "$ORFS_ROOT"
