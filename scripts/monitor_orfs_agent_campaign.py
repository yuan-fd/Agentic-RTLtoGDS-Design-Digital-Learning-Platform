#!/usr/bin/env python3
"""Read-only periodic status receipt for a frozen ORFS-Agent campaign.

This is deliberately outside Runtime authority: it never queues, cancels,
retries, or edits an experiment.  It only snapshots already durable facts for
an operator who needs long-running campaign supervision.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _unit_fields(unit: str) -> dict[str, str]:
    completed = subprocess.run(
        ["systemctl", "--user", "show", unit, "-p", "ActiveState", "-p", "SubState",
         "-p", "Result", "-p", "MainPID", "-p", "ExecMainStatus", "-p", "ExecMainExitTimestamp"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )
    fields = {key: value for line in completed.stdout.splitlines() if "=" in line
              for key, value in [line.split("=", 1)]}
    return {"query_returncode": str(completed.returncode), **fields}


def _campaign(root: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "root": str(root), "exists": root.is_dir(),
        "canonical_evaluator_count": len(list(root.rglob("common_evaluation.json"))) if root.is_dir() else 0,
    }
    database = root / "runtime.db"
    if not database.is_file():
        result["runtime_db"] = "absent"
        return result
    try:
        with sqlite3.connect(database) as connection:
            result["runtime_db"] = "present"
            result["run_status_counts"] = dict(connection.execute(
                "select status,count(*) from runtime_runs group by status"
            ).fetchall())
            result["role_status_counts"] = [
                {"role": role, "status": status, "count": count}
                for role, status, count in connection.execute(
                    "select json_extract(task_spec_json,'$.labels.external_l2_role'),status,count(*) "
                    "from runtime_runs group by 1,2 order by 1,2"
                ).fetchall()
            ]
            result["attempt_status_counts"] = dict(connection.execute(
                "select status,count(*) from runtime_attempts group by status"
            ).fetchall())
    except sqlite3.Error as exc:
        result["runtime_db_error"] = f"{type(exc).__name__}: {exc}"
    return result


def _summary(receipt: dict[str, Any]) -> str:
    """Human-readable mirror of the immutable JSON monitor receipt."""
    def counts(value: dict[str, Any]) -> str:
        items = value.get("run_status_counts") or {}
        return ", ".join(f"{key}={items[key]}" for key in sorted(items)) or "not started"
    formal = receipt["formal"]
    control = receipt["control"]
    unit = receipt["unit_status"]
    return "\n".join((
        "# ORFS-Agent v7 hourly supervision",
        "",
        f"- Observed (UTC): {receipt['observed_at']}",
        f"- Service: {unit.get('ActiveState', 'unknown')}/{unit.get('SubState', 'unknown')}",
        f"- Formal arm: {counts(formal)}; canonical evaluator artifacts={formal['canonical_evaluator_count']}",
        f"- Random-control arm: {counts(control)}; canonical evaluator artifacts={control['canonical_evaluator_count']}",
        f"- Aggregate comparison available: {'yes' if receipt['aggregate']['exists'] else 'no'}",
        "",
        "The JSON receipt in this directory remains the machine-readable audit source.",
        "",
    ))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--unit", required=True)
    parser.add_argument("--formal", type=Path, required=True)
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--aggregate", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    receipt = {
        "schema_version": 1,
        "kind": "read-only-orfs-agent-campaign-hourly-monitor",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "unit": args.unit,
        "unit_status": _unit_fields(args.unit),
        "formal": _campaign(args.formal.expanduser().resolve()),
        "control": _campaign(args.control.expanduser().resolve()),
        "aggregate": {
            "path": str(args.aggregate.expanduser().resolve()),
            "exists": args.aggregate.is_file(),
            "size_bytes": args.aggregate.stat().st_size if args.aggregate.is_file() else 0,
        },
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for path in (output / f"{stamp}.json", output / "latest.json"):
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        temporary.replace(path)
    for path in (output / f"{stamp}.md", output / "latest.md"):
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(_summary(receipt), encoding="utf-8")
        temporary.replace(path)
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
