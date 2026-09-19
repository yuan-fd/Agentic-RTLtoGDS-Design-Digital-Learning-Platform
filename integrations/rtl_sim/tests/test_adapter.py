from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
ADAPTER = ROOT / "adapter.py"


def write_request(workspace: Path) -> None:
    (workspace / "rtl").mkdir()
    (workspace / "verification").mkdir()
    (workspace / "rtl/counter.sv").write_text("module counter; endmodule\n", encoding="utf-8")
    (workspace / "verification/oracle.sv").write_text("module oracle; endmodule\n", encoding="utf-8")
    (workspace / "adapter_request.json").write_text(json.dumps({
        "schema_version": 1,
        "plugin": {"plugin_id": "rtl-sim", "plugin_version": "1.0.0"},
        "task": {"schema_version": 3, "task_id": "sim-1", "project_id": "teaching-m1",
                 "design_id": "counter", "plugin_id": "rtl-sim", "inputs": {
                     "rtl_path": "rtl/counter.sv", "testbench_path": "verification/oracle.sv",
                     "top": "counter", "simulation_top": "counter_tb",
                     "spec_id": "spec-counter", "verification_id": "verify-counter-v1",
                 }, "parameters": {}, "expected_artifacts": ["simulation_report", "log"]},
    }), encoding="utf-8")


def run(workspace: Path, env: dict[str, str] | None = None) -> tuple[int, dict]:
    result = workspace / "adapter_result.json"
    completed = subprocess.run(
        [sys.executable, str(ADAPTER), "--request", "adapter_request.json", "--result", "adapter_result.json"],
        cwd=workspace, env={**os.environ, **(env or {})}, capture_output=True, text=True, check=False,
    )
    assert result.is_file(), completed.stderr
    return completed.returncode, json.loads(result.read_text(encoding="utf-8"))


def tools(tmp_path: Path, *, verilator_code: int = 0) -> dict[str, str]:
    root = tmp_path / "tools"
    root.mkdir()
    path = root / "verilator"
    path.write_text(
        "#!/bin/sh\n"
        "while [ $# -gt 0 ]; do\n"
        "  if [ \"$1\" = \"-o\" ]; then shift; printf '#!/bin/sh\\necho TB_SUMMARY total=1 errors=0\\necho PASS\\n' > \"$1\"; chmod +x \"$1\"; fi\n"
        "  shift\n"
        f"done\nexit {verilator_code}\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return {"RTL_SIM_VERILATOR": str(path)}


def test_missing_tools_fail_closed(tmp_path: Path) -> None:
    write_request(tmp_path)

    code, result = run(tmp_path, {"RTL_SIM_VERILATOR": ""})

    assert code == 3
    assert result["failure"]["category"] == "configuration_error"


def test_simulation_success_registers_report_and_log(tmp_path: Path) -> None:
    write_request(tmp_path)

    code, result = run(tmp_path, tools(tmp_path))

    assert code == 0
    assert result["status"] == "succeeded"
    assert {item["kind"] for item in result["artifacts"]} == {"simulation_report", "log"}


def test_simulation_tool_failure_is_not_a_pass(tmp_path: Path) -> None:
    write_request(tmp_path)

    code, result = run(tmp_path, tools(tmp_path, verilator_code=5))

    assert code == 5
    assert result["status"] == "failed"
    assert result["failure"]["category"] == "simulation_failed"


def test_compiler_exit_zero_without_an_image_is_not_a_pass(tmp_path: Path) -> None:
    write_request(tmp_path)
    tool_root = tmp_path / "empty-tools"
    tool_root.mkdir()
    compiler = tool_root / "verilator"
    compiler.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    compiler.chmod(compiler.stat().st_mode | stat.S_IXUSR)

    code, result = run(tmp_path, {"RTL_SIM_VERILATOR": str(compiler)})

    assert code == 1
    assert result["failure"]["message"] == "verilator completed without producing a simulation image"
