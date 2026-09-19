#!/usr/bin/env python3
"""Fixed Verilator simulation Toolkit for the v2 foundation."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_result(path: Path, payload: dict[str, Any], started: str) -> None:
    path.write_text(json.dumps({"schema_version": 3, "started_at": started,
                                "ended_at": now(), **payload}, indent=2), encoding="utf-8")


def fail(path: Path, started: str, category: str, message: str, code: int = 1,
         artifacts: list[dict[str, str]] | None = None) -> int:
    write_result(path, {"status": "failed", "exit_code": code,
                        "artifacts": artifacts or [], "metrics": [],
                        "failure": {"category": category, "message": message, "retryable": False}}, started)
    return code


def staged(root: Path, value: object, name: str) -> Path:
    if not isinstance(value, str) or not value or value.startswith(("/", "\\")):
        raise ValueError(f"{name} must be a relative staged input")
    parts = value.replace("\\", "/").split("/")
    if ".." in parts or not all(part and part != "." for part in parts):
        raise ValueError(f"{name} must stay inside the staged workspace")
    path = (root / Path(*parts)).resolve()
    path.relative_to(root.resolve())
    if not path.is_file() or path.stat().st_size == 0:
        raise FileNotFoundError(f"staged {name} is missing or empty")
    return path


def executable(name: str) -> Path:
    value = os.environ.get(name, "")
    if not value:
        raise FileNotFoundError(f"{name} is not configured")
    path = Path(value).expanduser().resolve()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise FileNotFoundError(f"{name} is not executable")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--result", required=True)
    args = parser.parse_args()
    started = now()
    result = Path(args.result).expanduser().resolve()
    root = result.parent
    try:
        payload = json.loads(Path(args.request).expanduser().resolve().read_text(encoding="utf-8"))
        inputs = payload["task"]["inputs"]
        top = inputs["top"]
        if not isinstance(top, str) or not IDENTIFIER.fullmatch(top):
            raise ValueError("top must be a bounded identifier")
        rtl = staged(root, inputs["rtl_path"], "rtl_path")
        testbench = staged(root, inputs["testbench_path"], "testbench_path")
        simulation_top = inputs["simulation_top"]
        if not isinstance(simulation_top, str) or not IDENTIFIER.fullmatch(simulation_top):
            raise ValueError("simulation_top must be a bounded identifier")
        verilator = executable("RTL_SIM_VERILATOR")
        output = root / "outputs"
        output.mkdir(exist_ok=True)
        compiled = output / "simulation.bin"
        log = output / "simulation.log"
        commands = (("verilator", [str(verilator), "--binary", "--sv", "--top-module",
                                    simulation_top, "-o", str(compiled), str(rtl), str(testbench)]),
                    ("simulation", [str(compiled)]))
        rows = []
        with log.open("w", encoding="utf-8") as stream:
            for name, command in commands:
                stream.write("$ " + " ".join(command) + "\n")
                completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           text=True, check=False)
                stream.write(completed.stdout)
                rows.append({"step": name, "exit_code": completed.returncode})
                if completed.returncode != 0:
                    return fail(result, started, "simulation_failed", f"{name} failed",
                                completed.returncode or 1, [{"kind": "log", "path": "outputs/simulation.log"}])
                if name == "verilator" and (not compiled.is_file() or compiled.stat().st_size == 0):
                    return fail(result, started, "simulation_failed",
                                "verilator completed without producing a simulation image", 1,
                                [{"kind": "log", "path": "outputs/simulation.log"}])
        report = output / "simulation.json"
        report.write_text(json.dumps({"top": top, "simulation_top": simulation_top,
                                      "steps": rows, "status": "passed"}, indent=2), encoding="utf-8")
        write_result(result, {"status": "succeeded", "exit_code": 0,
                              "artifacts": [{"kind": "simulation_report", "path": "outputs/simulation.json"},
                                            {"kind": "log", "path": "outputs/simulation.log"}],
                              "metrics": [{"name": "rtl.simulation", "value": 1, "unit": "pass", "context": {}}],
                              "failure": None, "provenance": {"toolkit": "rtl-sim", "steps": rows}}, started)
        return 0
    except (KeyError, TypeError, ValueError, FileNotFoundError, OSError) as exc:
        return fail(result, started, "configuration_error", f"{type(exc).__name__}: {exc}", 3)


if __name__ == "__main__":
    raise SystemExit(main())
