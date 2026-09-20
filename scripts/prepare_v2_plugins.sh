#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
V2_ROOT="${OPENROAD_V2_ROOT:-$ROOT/../openroad-platform-v2}"
ORFS_ROOT="${AGENTICEDA_ORFS_ROOT:-$ROOT/../agenticeda-orfs}"
PLUGINS_ROOT="${OPENROAD_V2_PLUGINS_ROOT:-$ROOT/.local/state/openroad-teaching/v2/plugins}"

mkdir -p "$PLUGINS_ROOT"
ln -s "$V2_ROOT/plugins/rtl-sim" "$PLUGINS_ROOT/rtl-sim"
ln -s "$V2_ROOT/plugins/rtl-verify" "$PLUGINS_ROOT/rtl-verify"
ln -s "$ORFS_ROOT/orfs" "$PLUGINS_ROOT/orfs"
ln -s "$ORFS_ROOT/orfs-evaluator" "$PLUGINS_ROOT/orfs-evaluator"
printf '%s\n' "$PLUGINS_ROOT"
