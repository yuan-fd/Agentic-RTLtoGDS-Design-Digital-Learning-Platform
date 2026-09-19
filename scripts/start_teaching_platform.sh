#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/packages/contracts/src:$ROOT/apps/m1_rtl_to_gds/src${PYTHONPATH:+:$PYTHONPATH}"

exec python3 -m openroad_app_m1 \
  --serve \
  --database "${M1_DATABASE:-$ROOT/.local/m1.sqlite}" \
  --v2-url "${OPENROAD_V2_URL:-http://127.0.0.1:8700}" \
  --host "${M1_HOST:-127.0.0.1}" \
  --port "${M1_PORT:-8101}"
