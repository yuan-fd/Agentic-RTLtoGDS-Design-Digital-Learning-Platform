#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT="${ACCEPTANCE_OUTPUT:-$ROOT/acceptance/reports}"
CHECKOUT="$(mktemp -d "${TMPDIR:-/tmp}/teaching-acceptance.XXXXXX")"
mkdir -p "$OUTPUT"
trap 'rm -rf "$CHECKOUT"' EXIT

git clone --no-local --quiet "$ROOT" "$CHECKOUT/repo"
[[ -z "$(git -C "$CHECKOUT/repo" status --porcelain)" ]] || { echo 'clean checkout is dirty' >&2; exit 1; }

status=PASS
checks=()
add_check() { checks+=("$1|$2|$3"); if [[ "$2" != PASS && "$2" != NOT_APPLICABLE ]]; then status=FAIL; fi; }
for module in m1_rtl_to_gds m2_rtl_comparison m3_orfs_comparison m4_script_lab; do
  [[ -f "$CHECKOUT/repo/apps/$module/pyproject.toml" ]] && add_check "$module-pyproject" PASS "independent pyproject" || add_check "$module-pyproject" FAIL "missing pyproject"
done
if rg -n 'openroad_app_m[234]' "$CHECKOUT/repo/apps/m1_rtl_to_gds"; then add_check sibling-import-m1 FAIL 'M1 imports a sibling app'; else add_check sibling-import-m1 PASS 'no sibling import'; fi
if rg -n 'openroad_app_m[134]' "$CHECKOUT/repo/apps/m2_rtl_comparison" | rg -v 'openroad_app_m2'; then add_check sibling-import-m2 FAIL 'sibling app import found'; else add_check sibling-import-m2 PASS 'no sibling app import'; fi
if rg -n 'openroad_app_m[124]' "$CHECKOUT/repo/apps/m3_orfs_comparison" | rg -v 'openroad_app_m3'; then add_check sibling-import-m3 FAIL 'sibling app import found'; else add_check sibling-import-m3 PASS 'no sibling app import'; fi
if rg -n 'openroad_app_m[123]' "$CHECKOUT/repo/apps/m4_script_lab" | rg -v 'openroad_app_m4'; then add_check sibling-import-m4 FAIL 'sibling app import found'; else add_check sibling-import-m4 PASS 'no sibling app import'; fi
if rg -n 'openroad-platform-v2|runtime\.db' "$CHECKOUT/repo/apps"; then add_check v2-db-boundary FAIL 'teaching app references v2 database'; else add_check v2-db-boundary PASS 'v2 is HTTP-only'; fi

set +e
(cd "$CHECKOUT/repo" && PYTHONPATH="packages/contracts/src:apps/m1_rtl_to_gds/src" python3 -m pytest -q --junitxml="$OUTPUT/test-results.xml")
test_status=$?
set -e
if [[ "$test_status" -eq 0 ]]; then add_check clean-checkout-tests PASS 'full teaching test suite'; else add_check clean-checkout-tests FAIL "pytest exit $test_status"; fi

python3 - "$OUTPUT" "$status" "${checks[@]}" <<'PY'
import json, sys
from pathlib import Path
output = Path(sys.argv[1]); status = sys.argv[2]
checks = []
for item in sys.argv[3:]:
    name, value, detail = item.split('|', 2)
    checks.append({'check': name, 'status': value, 'detail': detail})
payload = {'checks': checks, 'functional_acceptance': 'PASS' if status == 'PASS' else 'FAIL', 'production_deployment_readiness': 'FAIL'}
(output / 'audit-report.json').write_text(json.dumps(payload, indent=2) + '\n')
(output / 'artifact-manifest.json').write_text(json.dumps({'source': 'independent clean checkout', 'checks': checks}, indent=2) + '\n')
lines = ['# Independent Teaching Platform Audit', '', f'Functional acceptance: {payload["functional_acceptance"]}', 'Production deployment readiness: FAIL', '', '## Checks', '']
lines += [f'- `{x["status"]}` {x["check"]}: {x["detail"]}' for x in checks]
(output / 'audit-report.md').write_text('\n'.join(lines) + '\n')
PY

if [[ -f "$OUTPUT/ux-report.json" ]]; then cp "$OUTPUT/ux-report.json" "$OUTPUT/ux-report.snapshot.json"; fi
exit "$([[ "$status" == PASS ]] && echo 0 || echo 1)"
