#!/usr/bin/env python3
"""Fixed RTL compile/lint Toolkit for the v2 execution foundation."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
CHECKS = ("verilator-lint", "yosys-check")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_result(path: Path, payload: dict[str, Any], started: str) -> None:
    path.write_text(json.dumps({
        "schema_version": 3, "started_at": started, "ended_at": now(), **payload,
    }, indent=2), encoding="utf-8")


def fail(path: Path, started: str, category: str, message: str, code: int = 1,
         artifacts: list[dict[str, str]] | None = None) -> int:
    write_result(path, {
        "status": "failed", "exit_code": code, "artifacts": artifacts or [], "metrics": [],
        "failure": {"category": category, "message": message, "retryable": False},
        "provenance": {"toolkit": "rtl-verify", "checks": list(CHECKS)},
    }, started)
    return code


def relative_input(root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value or value.startswith(("/", "\\")):
        raise ValueError("rtl_path must be a relative staged input")
    parts = value.replace("\\", "/").split("/")
    if ".." in parts or not all(part and part not in {".", ".."} for part in parts):
        raise ValueError("rtl_path must stay inside the staged workspace")
    path = (root / Path(*parts)).resolve()
    path.relative_to(root.resolve())
    if not path.is_file() or path.stat().st_size == 0:
        raise FileNotFoundError("staged RTL input is missing or empty")
    return path


def executable(name: str) -> Path:
    value = os.environ.get(name, "")
    if not value:
        raise FileNotFoundError(f"{name} is not configured")
    path = Path(value).expanduser().resolve()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise FileNotFoundError(f"{name} is not an executable file")
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
        task = payload["task"]
        inputs = task["inputs"]
        top = inputs["top"]
        if not isinstance(top, str) or not IDENTIFIER.fullmatch(top):
            raise ValueError("top must be a bounded identifier")
        checks = tuple(inputs.get("compile_checks") or ())
        if checks != CHECKS:
            raise ValueError(f"compile_checks must be exactly {list(CHECKS)}")
        rtl = relative_input(root, inputs["rtl_path"])
        verilator = executable("RTL_VERIFY_VERILATOR")
        yosys = executable("YOSYS_BIN")
        output = root / "outputs"
        output.mkdir(exist_ok=True)
        verified = output / "verified_design.sv"
        shutil.copy2(rtl, verified)
        log = output / "verification.log"
        rows = []
        commands = (
            ("verilator-lint", [str(verilator), "--lint-only", "--sv", "--top-module", top, str(rtl)]),
            ("yosys-check", [str(yosys), "-Q", "-p", f"read_verilog -sv {rtl}; hierarchy -top {top}; proc; check"]),
        )
        with log.open("w", encoding="utf-8") as stream:
            for check, command in commands:
                stream.write("$ " + " ".join(command) + "\n")
                completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           text=True, check=False)
                stream.write(completed.stdout)
                rows.append({"check": check, "exit_code": completed.returncode})
                if completed.returncode != 0:
                    return fail(
                        result, started, "rtl_verification_failed", f"{check} failed",
                        completed.returncode or 1,
                        [{"kind": "log", "path": "outputs/verification.log"}],
                    )
        report = output / "verification.json"
        report.write_text(json.dumps({"top": top, "checks": rows}, indent=2), encoding="utf-8")
        write_result(result, {
            "status": "succeeded", "exit_code": 0,
            "artifacts": [
                {"kind": "rtl", "path": "outputs/verified_design.sv"},
                {"kind": "verification_report", "path": "outputs/verification.json"},
                {"kind": "log", "path": "outputs/verification.log"},
            ],
            "metrics": [{"name": "rtl.compile_lint", "value": 1, "unit": "pass", "context": {}}],
            "failure": None,
            "provenance": {"toolkit": "rtl-verify", "checks": rows},
        }, started)
        return 0
    except (KeyError, TypeError, ValueError, FileNotFoundError, OSError) as exc:
        return fail(result, started, "configuration_error", f"{type(exc).__name__}: {exc}", 3)


if __name__ == "__main__":
    raise SystemExit(main())
