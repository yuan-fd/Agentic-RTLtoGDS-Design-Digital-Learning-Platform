from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from openroad_platform_contracts import ExperimentPlan, PluginManifest
from openroad_platform_execution import agenticpd_plugin_manifest, build_agenticpd_task
from openroad_platform_execution.agenticpd_adapter import _candidate
from openroad_platform_execution.registry import PluginRegistry


def test_agenticpd_task_never_persists_credential():
    task = build_agenticpd_task(project_id="p5", design_id="adder", mode="real")
    assert "DEEPSEEK_API_KEY" not in json.dumps(task.to_dict()).replace(
        '"credential_env": "DEEPSEEK_API_KEY"', ""
    )
    assert task.resources["credential_env"] == "DEEPSEEK_API_KEY"


def test_candidate_only_activates_unambiguous_orfs_parameter():
    candidate = _candidate({
        "trial_id": "abc12345",
        "params": {"FP": {"CORE_UTILIZATION": 35, "CORE_ASPECT_RATIO": 0.85},
                   "PL": {"PLACE_DENSITY_LB_ADDON": 0.08}},
    })
    assert candidate.parameters == {"core_utilization_pct": 35.0}
    assert candidate.unsupported_parameters == {
        "FP.CORE_ASPECT_RATIO": 0.85, "PL.PLACE_DENSITY_LB_ADDON": 0.08,
    }
    plan = ExperimentPlan(
        plan_id="p", producer="agenticpd", design_id="adder", platform="nangate45",
        baseline_parameters={"core_utilization_pct": 38.0}, candidates=(candidate,),
        max_child_runs=1,
    )
    assert ExperimentPlan.from_dict(plan.to_dict()) == plan


def test_agenticpd_executable_manifest_fails_before_source_or_credential_access(tmp_path):
    missing_source = tmp_path / "must-not-be-read"
    with pytest.raises(PermissionError, match="source-audit-only"):
        agenticpd_plugin_manifest(
            missing_source, python_executable=tmp_path / "must-not-be-read-python",
            credential="must-not-be-persisted",
        )
    assert not missing_source.exists()


def test_agenticpd_static_record_is_not_an_executable_plugin_manifest():
    root = Path(__file__).resolve().parents[1] / "integrations" / "agenticpd"
    payload = json.loads((root / "agenticpd.plugin.json").read_text())
    assert payload["execution_class"] == "source-audit-only"
    assert payload["license"] is None
    with pytest.raises(ValueError, match="Unknown PluginManifest fields"):
        PluginManifest.from_dict(payload)
    with pytest.raises(ValueError, match="Unknown PluginManifest fields"):
        PluginRegistry.from_directory(root)
