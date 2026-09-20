#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/packages/contracts/src:$ROOT/apps/m1_rtl_to_gds/src${PYTHONPATH:+:$PYTHONPATH}"

STATE_ROOT="${M1_STATE_ROOT:-${XDG_STATE_HOME:-$ROOT/.local/state}/openroad-teaching}"
mkdir -p "$STATE_ROOT/logs" "$STATE_ROOT/backups"
DATABASE="${M1_DATABASE:-$STATE_ROOT/m1.sqlite}"
V2_URL="${OPENROAD_V2_URL:-http://127.0.0.1:8700}"
HOST="${M1_HOST:-127.0.0.1}"
PORT="${M1_PORT:-8101}"
printf 'M1 database: %s\nM1 endpoint: http://%s:%s\nv2 endpoint: %s\n' "$DATABASE" "$HOST" "$PORT" "$V2_URL" >&2

exec python3 -m openroad_app_m1 \
  --serve \
  --database "$DATABASE" \
  --v2-url "$V2_URL" \
  --v2-token "${OPENROAD_V2_TOKEN:-}" \
  --host "$HOST" \
  --port "$PORT"
