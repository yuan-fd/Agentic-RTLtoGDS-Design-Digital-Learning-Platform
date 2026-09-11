#!/usr/bin/env python3
"""Check the server-managed dependencies needed by the teaching platform."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_MODULES = ("numpy", "scipy", "torch", "optuna", "botorch", "gpytorch", "graphviz")


def _tool(name: str, override: str | None) -> dict[str, object]:
    value = Path(override).expanduser() if override else None
    fallback = ROOT.parent / ".local" / "opt" / "openroad-rtl-tools" / "bin" / name
    resolved = str(value.resolve()) if value else (shutil.which(name) or (str(fallback) if fallback.is_file() else None))
    path = Path(resolved) if resolved else None
    return {"name": name, "path": str(path) if path else None,
            "available": bool(path and path.is_file() and os.access(path, os.X_OK))}


def doctor() -> dict[str, object]:
    modules = {name: bool(importlib.util.find_spec(name)) for name in REQUIRED_MODULES}
    tools = {
        "openroad": _tool("openroad", os.environ.get("OPENROAD_BIN")),
        "yosys": _tool("yosys", os.environ.get("YOSYS_BIN")),
        "verilator": _tool("verilator", os.environ.get("VERILATOR_BIN")),
        "iverilog": _tool("iverilog", os.environ.get("IVERILOG_BIN")),
    }
    orfs = Path(os.environ.get("ORFS_ROOT", str(ROOT.parent / "OpenROAD-flow-scripts"))).expanduser()
    result = {"schema_version": 1, "root": str(ROOT), "python": os.sys.executable,
              "modules": modules, "tools": tools,
              "orfs_root": str(orfs), "orfs_makefile": (orfs / "flow" / "Makefile").is_file()}
    result["passed"] = all(modules.values()) and all(item["available"] for item in tools.values()) and result["orfs_makefile"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print the machine-readable report")
    args = parser.parse_args()
    result = doctor()
    print(json.dumps(result, indent=2, sort_keys=True) if args.json else
          ("teaching platform environment: OK" if result["passed"] else "teaching platform environment: INCOMPLETE"))
    if not result["passed"] and not args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
