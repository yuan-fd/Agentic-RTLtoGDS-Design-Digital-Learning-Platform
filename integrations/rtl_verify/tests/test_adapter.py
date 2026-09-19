from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
ADAPTER = ROOT / "adapter.py"


def request(workspace: Path) -> Path:
    path = workspace / "adapter_request.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "plugin": {"plugin_id": "rtl-verify", "plugin_version": "1.0.0"},
        "task": {
            "schema_version": 3,
            "task_id": "verify-1",
            "project_id": "teaching-m1",
            "design_id": "counter",
            "plugin_id": "rtl-verify",
            "inputs": {
                "rtl_path": "rtl/counter.sv",
                "top": "counter",
                "spec_id": "spec-counter",
                "verification_id": "verify-counter-v1",
                "compile_checks": ["verilator-lint", "yosys-check"],
            },
            "parameters": {},
            "staged_inputs": [],
            "expected_artifacts": ["rtl", "verification_report", "log"],
        },
    }), encoding="utf-8")
    return path


def run_adapter(workspace: Path, env: dict[str, str] | None = None) -> tuple[int, dict]:
    result = workspace / "adapter_result.json"
    completed = subprocess.run(
        [sys.executable, str(ADAPTER), "--request", "adapter_request.json", "--result", "adapter_result.json"],
        cwd=workspace, env={**os.environ, **(env or {})},
        capture_output=True, text=True, check=False,
    )
    assert result.is_file(), completed.stderr
    return completed.returncode, json.loads(result.read_text(encoding="utf-8"))


def test_missing_toolchain_is_a_real_configuration_failure(tmp_path: Path) -> None:
    (tmp_path / "rtl").mkdir()
    (tmp_path / "rtl/counter.sv").write_text("module counter; endmodule\n", encoding="utf-8")
    request(tmp_path)

    code, result = run_adapter(tmp_path, {"RTL_VERIFY_VERILATOR": "", "YOSYS_BIN": ""})

    assert code == 3
    assert result["status"] == "failed"
    assert result["failure"]["category"] == "configuration_error"
    assert result["artifacts"] == []


def test_success_registers_only_real_output_artifacts(tmp_path: Path) -> None:
    (tmp_path / "rtl").mkdir()
    (tmp_path / "rtl/counter.sv").write_text("module counter; endmodule\n", encoding="utf-8")
    request(tmp_path)
    tools = tmp_path / "tools"
    tools.mkdir()
    for name in ("verilator", "yosys"):
        path = tools / name
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    code, result = run_adapter(tmp_path, {
        "RTL_VERIFY_VERILATOR": str(tools / "verilator"),
        "YOSYS_BIN": str(tools / "yosys"),
    })

    assert code == 0
    assert result["status"] == "succeeded"
    assert {item["kind"] for item in result["artifacts"]} == {"rtl", "verification_report", "log"}
    assert all((tmp_path / item["path"]).is_file() for item in result["artifacts"])


def test_path_escape_is_rejected_before_tool_execution(tmp_path: Path) -> None:
    (tmp_path / "rtl").mkdir()
    (tmp_path / "rtl/counter.sv").write_text("module counter; endmodule\n", encoding="utf-8")
    request_path = request(tmp_path)
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    payload["task"]["inputs"]["rtl_path"] = "../counter.sv"
    request_path.write_text(json.dumps(payload), encoding="utf-8")

    code, result = run_adapter(tmp_path)

    assert code == 3
    assert result["failure"]["category"] == "configuration_error"


def test_tool_failure_keeps_the_verification_log_as_partial_evidence(tmp_path: Path) -> None:
    (tmp_path / "rtl").mkdir()
    (tmp_path / "rtl/counter.sv").write_text("module counter; endmodule\n", encoding="utf-8")
    request(tmp_path)
    tools = tmp_path / "tools"
    tools.mkdir()
    for name, code in (("verilator", 4), ("yosys", 0)):
        path = tools / name
        path.write_text(f"#!/bin/sh\nexit {code}\n", encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    code, result = run_adapter(tmp_path, {
        "RTL_VERIFY_VERILATOR": str(tools / "verilator"),
        "YOSYS_BIN": str(tools / "yosys"),
    })

    assert code == 4
    assert result["status"] == "failed"
    assert result["artifacts"] == [{"kind": "log", "path": "outputs/verification.log"}]
