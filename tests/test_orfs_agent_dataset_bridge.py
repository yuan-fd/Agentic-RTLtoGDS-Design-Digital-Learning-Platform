from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from openroad_platform_contracts.platform import PluginManifest


ROOT = Path(__file__).parents[1]
ADAPTER_PATH = ROOT / "integrations/orfs_agent/orfs_agent_adapter.py"
SPEC = importlib.util.spec_from_file_location("orfs_agent_dataset_bridge", ADAPTER_PATH)
assert SPEC and SPEC.loader
bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge)


def test_row_is_a_flat_view_that_retains_runtime_evidence_references():
    row = bridge._row({
        "observation_id": "run-001", "feasible": True,
        "artifact_refs": ["runtime:run-001:report"],
        "parameters": {"clock_period_ns": 1.26, "core_utilization_pct": 40},
        "metrics": {"setup_wns_ns": -.11, "drc_errors": 0, "area_um2": 1200.0},
    }, design="ibex", platform="asap7")
    assert row["circuit"] == "ibex"
    assert row["ECP_final"] == pytest.approx(1.37)
    assert row["platform_observation_id"] == "run-001"
    assert row["platform_artifact_refs"] == ["runtime:run-001:report"]


def test_bridge_refuses_implicit_source_selection(monkeypatch):
    monkeypatch.delenv("ORFS_AGENT_SOURCE", raising=False)
    with pytest.raises(ValueError, match="explicit clean detached checkout"):
        bridge._checked_source(bridge._load_lock())


def test_bridge_refuses_the_source_audit_cache(monkeypatch):
    lock = bridge._load_lock()
    monkeypatch.setenv("ORFS_AGENT_SOURCE", str(ROOT / lock["cache_path"]))
    with pytest.raises(ValueError, match="source-audit cache"):
        bridge._checked_source(lock)


def test_dataset_manifest_does_not_admit_an_optimizer_capability():
    manifest = PluginManifest.from_dict(json.loads(
        (ROOT / "integrations/orfs_agent/orfs_agent.plugin.json").read_text(encoding="utf-8")))
    assert manifest.capabilities == ("optimizer.l2.dataset-bridge",)
    assert {rule["kind"] for rule in manifest.artifact_rules} == {
        "optimizer_dataset", "optimizer_input_manifest", "upstream_source_lock", "report", "log"}


def test_main_materializes_only_dataset_from_a_clean_detached_source(monkeypatch, tmp_path):
    source = tmp_path / "upstream"
    source.mkdir()
    (source / "LICENSE").write_text("BSD 3-Clause License\n", encoding="utf-8")
    for command in (("git", "init", "-q"), ("git", "config", "user.email", "test@example.invalid"),
                    ("git", "config", "user.name", "test"), ("git", "add", "LICENSE"),
                    ("git", "commit", "-qm", "source")):
        subprocess.run(command, cwd=source, check=True)
    commit = subprocess.check_output(("git", "rev-parse", "HEAD"), cwd=source, text=True).strip()
    subprocess.run(("git", "checkout", "--detach", "-q", commit), cwd=source, check=True)
    monkeypatch.setenv("ORFS_AGENT_SOURCE", str(source))
    monkeypatch.setattr(bridge, "_load_lock", lambda: {
        "plugin_id": "orfs-agent", "commit": commit, "license": "BSD-3-Clause",
        "repository": "https://example.invalid/orfs-agent.git", "cache_path": ".external-src/audit-cache",
    })
    request = tmp_path / "request.json"; result = tmp_path / "result.json"
    request.write_text(json.dumps({"plugin": {"plugin_id": "orfs-agent"}, "task": {
        "task_id": "dataset-001", "plugin_id": "orfs-agent", "inputs": {
            "design": "ibex", "platform": "asap7", "objective": "ECP_final", "observations": [{
                "run_id": "run-001", "parameters": {"clock_period_ns": 1.0},
                "metrics": {"setup_wns_ns": -.1}, "artifact_refs": ["runtime:run-001:qor"], "feasible": True,
            }],
        },
    }}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["bridge", "--request", str(request), "--result", str(result)])
    assert bridge.main() == 0
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["status"] == "succeeded"
    assert {item["kind"] for item in payload["artifacts"]} == {
        "optimizer_dataset", "optimizer_input_manifest", "upstream_source_lock"}
    assert "optimizer_candidates" not in result.read_text(encoding="utf-8")
