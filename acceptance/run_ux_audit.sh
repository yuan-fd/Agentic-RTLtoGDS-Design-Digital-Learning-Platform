#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT="${ACCEPTANCE_OUTPUT:-$ROOT/acceptance/reports}"
mkdir -p "$OUTPUT"
if [[ -z "${CHROMIUM_EXECUTABLE:-}" || ! -x "$CHROMIUM_EXECUTABLE" ]]; then
  echo "CHROMIUM_EXECUTABLE must point to the acceptance browser" >&2
  exit 2
fi
if [[ -z "${PLAYWRIGHT_NODE_MODULES:-}" ]]; then
  echo "PLAYWRIGHT_NODE_MODULES must point to an independent Playwright install" >&2
  exit 2
fi
ACCEPTANCE_OUTPUT="$OUTPUT" node "$ROOT/acceptance/ux_audit.cjs"
