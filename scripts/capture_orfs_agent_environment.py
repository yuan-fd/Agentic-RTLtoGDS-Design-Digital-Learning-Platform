#!/usr/bin/env python3
"""Record the bounded execution environment for one ORFS-Agent attempt.

This does not create an EDA process or alter an upstream source tree.  It
records the identity of the admitted sources and the tool binaries that a
separate Runtime attempt will use.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


PACKAGES = (
    "numpy", "pandas", "scikit-learn", "scipy", "anthropic",
    "python-dotenv", "scikit-optimize",
)
ENVIRONMENT_KEYS = (
    "LD_LIBRARY_PATH", "LIBRARY_PATH", "TCLLIBPATH", "PATH",
    "OPENROAD_EXE", "YOSYS_EXE", "FLOW_HOME", "WORK_HOME", "PDK_ROOT",
)


def _command(*command: str) -> str:
    return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT).strip()


def _git(root: Path) -> dict[str, str]:
    return {
        "path": str(root.resolve()),
        "commit": _command("git", "-C", str(root), "rev-parse", "HEAD"),
        "status": _command("git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--paper-orfs", type=Path, required=True)
    parser.add_argument("--openroad", type=Path, required=True)
    parser.add_argument("--yosys", type=Path, required=True)
    parser.add_argument("--design", required=True)
    parser.add_argument("--platform", required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite environment evidence: {args.output}")
    packages: dict[str, str] = {}
    for package in PACKAGES:
        try:
            packages[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            packages[package] = "MISSING"
    release = Path("/etc/os-release")
    manifest = {
        "schema_version": 1,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "design": args.design,
        "platform": args.platform,
        "host": {
            "architecture": platform.machine(),
            "kernel": platform.release(),
            "os_release": release.read_text(encoding="utf-8") if release.is_file() else None,
        },
        "python": {"executable": sys.executable, "version": sys.version, "packages": packages},
        "tools": {
            "openroad": {"path": str(args.openroad.resolve()), "version": _command(str(args.openroad), "-version")},
            "yosys": {"path": str(args.yosys.resolve()), "version": _command(str(args.yosys), "-V")},
        },
        "sources": {"orfs_agent": _git(args.source), "orfs": _git(args.paper_orfs)},
        "selected_environment": {key: os.environ[key] for key in ENVIRONMENT_KEYS if key in os.environ},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
