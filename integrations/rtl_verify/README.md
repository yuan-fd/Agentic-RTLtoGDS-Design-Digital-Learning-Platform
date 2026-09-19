# `rtl-verify` v2 Toolkit

This first-party Toolkit is a bounded compile/lint capability for the M1
teaching module. It executes exactly two registered checks:

1. Verilator `--lint-only --sv`;
2. Yosys hierarchy/proc/check.

It reads the RTL only from the v2 attempt workspace at the relative path in
the task inputs. It never accepts a host RTL path, shell command, arbitrary
check name, or user-supplied executable. Tool paths are operator-provided in
the v2 admitted environment.

The manifest is intentionally not an admission record. A v2 operator must
review the current repository commit, toolchain paths, license posture and
native smoke before adding an admission record. Until then, M1 must report the
Toolkit as unavailable; it cannot silently use the old monolithic API.

```bash
python3 -m pytest -q integrations/rtl_verify/tests
PYTHONPATH=/share/home/yuanwenjie/openroad-platform-v2/contracts/src:/share/home/yuanwenjie/openroad-platform-v2/core/registry/src \
  python3 -m openroad_platform_registry.validate integrations/rtl_verify
```
