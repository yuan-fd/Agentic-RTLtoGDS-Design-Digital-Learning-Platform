#!/usr/bin/env python3
"""Small operator commands for teaching-layer state only."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def backup(database: Path, output: Path) -> int:
    output.mkdir(parents=True, exist_ok=True)
    target = output / database.name
    source = sqlite3.connect(str(database))
    destination = sqlite3.connect(str(target))
    try:
        source.backup(destination)
        integrity = destination.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        destination.close()
        source.close()
    if integrity != "ok":
        raise SystemExit(f"backup integrity check failed: {integrity}")
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "database": str(database),
        "backup": str(target),
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "integrity_check": integrity,
    }
    (output / "backup.manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


def health(url: str) -> int:
    with urllib.request.urlopen(url.rstrip("/") + "/api/m1/health", timeout=10) as response:
        payload = json.loads(response.read())
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("status") == "ok" else 1


def disk(path: Path) -> int:
    usage = shutil.disk_usage(path)
    print(json.dumps({"path": str(path), "free_bytes": usage.free, "total_bytes": usage.total}, indent=2))
    return 0 if usage.free > 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    item = sub.add_parser("backup")
    item.add_argument("--database", type=Path, required=True)
    item.add_argument("--output", type=Path, required=True)
    item = sub.add_parser("health")
    item.add_argument("--url", required=True)
    item = sub.add_parser("disk")
    item.add_argument("--path", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "backup":
        return backup(args.database, args.output)
    if args.command == "health":
        return health(args.url)
    return disk(args.path)


if __name__ == "__main__":
    raise SystemExit(main())
