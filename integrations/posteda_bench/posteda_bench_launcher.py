#!/usr/bin/env python3
"""Resolve locked local PostEDA-Bench assets, then exec the adapter."""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    python = Path(sys.executable).resolve()
    adapter = ROOT / "integrations/posteda_bench/posteda_bench_adapter.py"
    source = ROOT / "var/external-sources/posteda-bench-51884e5-clean"
    lock = ROOT / "integrations/posteda_bench/source.lock.json"
    klayout = Path("/share/home/yuanwenjie/bin/klayout")
    for path in (python, adapter, source, lock, klayout):
        if not path.exists():
            raise FileNotFoundError(f"locked PostEDA runtime input is missing: {path}")
    environment = dict(os.environ)
    environment.update({
        "POSTEDA_BENCH_SOURCE": str(source),
        "POSTEDA_BENCH_KLAYOUT": str(klayout),
        "POSTEDA_BENCH_SOURCE_LOCK": str(lock),
        "POSTEDA_BENCH_SOURCE_LOCK_SHA256": hashlib.sha256(lock.read_bytes()).hexdigest(),
        "PYTHONDONTWRITEBYTECODE": "1", "NO_PROXY": "*", "no_proxy": "*",
        "PATH": os.pathsep.join((str(klayout.parent), "/usr/bin", "/bin")),
    })
    os.execve(str(python), [str(python), str(adapter), *sys.argv[1:]], environment)


if __name__ == "__main__":
    main()
