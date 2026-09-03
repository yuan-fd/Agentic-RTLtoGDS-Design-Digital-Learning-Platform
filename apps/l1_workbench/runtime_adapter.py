#!/usr/bin/env python3
"""Bounded Runtime plugin used only by the L1 vertical-slice smoke.

It is a real subprocess protocol endpoint, not a fake trace producer: Runtime
creates the workspace, invokes this program, records its exit code and admits
the returned artifact under the manifest allowlist.
"""
import argparse, json, time
from datetime import datetime, timezone
from pathlib import Path

parser = argparse.ArgumentParser(); parser.add_argument("--request", type=Path, required=True); parser.add_argument("--result", type=Path, required=True)
args = parser.parse_args(); request = json.loads(args.request.read_text())
if request["task"]["inputs"].get("bounded_mode") == "cancellable":
    time.sleep(4)
artifact = args.result.parent / "l1_tool_receipt.txt"
artifact.write_text("L1 bounded typed tool completed\n", encoding="utf-8")
now = datetime.now(timezone.utc).isoformat()
args.result.write_text(json.dumps({"schema_version": 1, "status": "succeeded", "exit_code": 0,
    "started_at": now, "ended_at": now, "metrics": [{"name": "l1_tool_runs", "value": 1, "unit": "count"}],
    "artifacts": [{"kind": "report", "path": artifact.name}], "failure": None,
    "provenance": {"adapter": "l1-workbench-runtime-adapter"}}), encoding="utf-8")
