from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.run_orfs_agent_systemd_campaign import _command, _validate_preflight


def test_systemd_supervisor_command_invokes_only_existing_campaign_controllers(tmp_path):
    command = _command(
        preflight_output=tmp_path / "preflight", reuse_preflight=None,
        supervisor_output=tmp_path / "supervisor",
        formal_output=tmp_path / "formal",
        control_output=tmp_path / "control",
        aggregate_output=tmp_path / "comparison.json",
        orfs_agent_source=None,
        max_parallel=8, orfs_cores_per_run=4, stage_timeout=7200, flow_timeout=14400,
    )
    assert command[1].endswith("run_orfs_agent_systemd_campaign.py")
    assert command[2] == "--worker"
    assert "--supervisor-output" in command
    assert ("--preflight-output" in command and "--formal-output" in command
            and "--control-output" in command and "--aggregate-output" in command)
    assert command[command.index("--stage-timeout") + 1] == "7200"
    assert command[command.index("--flow-timeout") + 1] == "14400"
    assert "run_orfs_agent_paper_campaign.py" not in command


def test_systemd_supervisor_can_reuse_only_a_completed_preflight_root(tmp_path):
    command = _command(
        preflight_output=None, reuse_preflight=tmp_path / "completed-preflight",
        supervisor_output=tmp_path / "supervisor",
        formal_output=tmp_path / "formal", control_output=tmp_path / "control",
        aggregate_output=tmp_path / "comparison.json", orfs_agent_source=tmp_path / "clean-source", max_parallel=8,
        orfs_cores_per_run=4, stage_timeout=7200, flow_timeout=14400,
    )
    assert "--reuse-preflight" in command
    assert "--preflight-output" not in command
    assert command[command.index("--orfs-agent-source") + 1] == str(tmp_path / "clean-source")


def test_supervisor_fails_closed_without_a_completed_hashed_preflight(tmp_path):
    with pytest.raises(RuntimeError, match="required receipt/report"):
        _validate_preflight(tmp_path)

    report = tmp_path / "target-feasibility-report.json"
    report.write_text(json.dumps({"kind": "report"}), encoding="utf-8")
    (tmp_path / "preflight-receipt.json").write_text(json.dumps({
        "status": "completed", "report_sha256": "not-the-report",
    }), encoding="utf-8")
    with pytest.raises(RuntimeError, match="digest mismatch"):
        _validate_preflight(tmp_path)

    digest = hashlib.sha256(report.read_bytes()).hexdigest()
    (tmp_path / "preflight-receipt.json").write_text(json.dumps({
        "status": "completed", "report_sha256": digest,
    }), encoding="utf-8")
    assert _validate_preflight(tmp_path) == report
