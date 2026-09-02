import hashlib
import json

import pytest

from openroad_platform_analysis.common_evaluator import (
    evaluate_orfs_run, write_immutable_evaluation,
)
from openroad_platform_analysis.orfs_protected_evaluator import ORFSProtectedEvaluator
from openroad_platform_analysis.parsers.stage_json import extract_metrics
from openroad_platform_contracts.platform import PluginManifest, TaskSpec


def _json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def _run(tmp_path, *, wns=0.1, include_power=True):
    logs, results = tmp_path / "logs", tmp_path / "results"
    logs.mkdir(parents=True); results.mkdir()
    for prefix in ("1_synth", "2_1_floorplan", "3_5_place_dp", "4_1_cts"):
        payload = {"design__instance__count": 1}
        if prefix == "2_1_floorplan":
            payload["run__flow__platform__time_units"] = "1ns"
        _json(logs / f"{prefix}.json", payload)
    _json(logs / "5_2_route.json", {
        "detailedroute__design__instance__count": 1,
        "detailedroute__route__drc_errors": 0,
    })
    finish = {
        "finish__design__instance__area": 123.0,
        "finish__design__die__area": 456.0,
        "finish__timing__setup__ws": wns,
    }
    if include_power:
        finish["finish__power__total"] = 0.25
    _json(logs / "6_report.json", finish)
    for name in ("6_final.odb", "6_final.def", "6_final.gds", "6_final.v"):
        (results / name).write_bytes(name.encode())
    sha = hashlib.sha256(b"identity").hexdigest()
    return evaluate_orfs_run(
        log_dir=logs, result_dir=results, platform="asap7", design="aes",
        design_identity_sha256=sha, effective_config_sha256=sha,
        or_seed=101, source_kind="native-platform", runtime_seconds=12.5,
    )


def test_common_evaluator_passes_complete_clean_run(tmp_path):
    value = _run(tmp_path)
    assert value["feasible"] is True
    assert value["metrics"]["instance_area_um2"] == 123.0
    assert len(value["artifacts"]) == 4
    assert all(len(item["sha256"]) == 64 for item in value["artifacts"])


def test_common_evaluator_never_treats_missing_metric_or_negative_wns_as_feasible(tmp_path):
    value = _run(tmp_path, wns=-0.01, include_power=False)
    assert value["feasible"] is False
    assert "setup_timing_violation" in value["gate"]["reasons"]
    assert value["gate"]["missing_metrics"] == ["power_W"]


def test_immutable_evaluation_allows_only_identical_retry(tmp_path):
    value = _run(tmp_path / "run")
    target = tmp_path / "evaluation.json"
    write_immutable_evaluation(target, value)
    write_immutable_evaluation(target, value)
    with pytest.raises(FileExistsError):
        write_immutable_evaluation(target, {**value, "feasible": False})


def test_common_evaluator_converts_asap7_ps_to_canonical_ns(tmp_path):
    value = _run(tmp_path, wns=-28.1865)
    floorplan = next((tmp_path / "logs").glob("2_1_floorplan.json"))
    payload = json.loads(floorplan.read_text())
    payload["run__flow__platform__time_units"] = "1ps"
    floorplan.write_text(json.dumps(payload))
    sha = hashlib.sha256(b"identity").hexdigest()
    value = evaluate_orfs_run(
        log_dir=tmp_path / "logs", result_dir=tmp_path / "results",
        platform="asap7", design="aes", design_identity_sha256=sha,
        effective_config_sha256=sha, or_seed=101, source_kind="native-platform",
        clock_period_ns=.380,
    )
    assert value["metrics"]["setup_wns_ns"] == pytest.approx(-.0281865)
    assert value["normalized_stage_evidence"]["units"]["time"] == {
        "status": "verified", "raw_values": ["1ps"],
        "canonical_unit": "ns", "scale_to_ns": .001,
    }


def test_common_evaluator_rejects_ambiguous_time_units(tmp_path):
    value = _run(tmp_path)
    floorplan = tmp_path / "logs/2_1_floorplan.json"
    payload = json.loads(floorplan.read_text())
    payload.pop("run__flow__platform__time_units")
    floorplan.write_text(json.dumps(payload))
    sha = hashlib.sha256(b"identity").hexdigest()
    value = evaluate_orfs_run(
        log_dir=tmp_path / "logs", result_dir=tmp_path / "results",
        platform="asap7", design="aes", design_identity_sha256=sha,
        effective_config_sha256=sha, or_seed=101, source_kind="native-platform",
    )
    assert value["feasible"] is False
    assert "unverified_time_unit" in value["gate"]["reasons"]


def test_workspace_and_common_parser_share_canonical_time_units(tmp_path):
    work = tmp_path / "work"
    logs = work / "logs/asap7/aes/base"; logs.mkdir(parents=True)
    designs = work / "designs/asap7/aes"; designs.mkdir(parents=True)
    (designs / "constraint.sdc").write_text(
        "create_clock -period 380 [get_ports clk]\n")
    _json(logs / "2_1_floorplan.json", {
        "run__flow__platform__time_units": "1ps",
        "floorplan__design__instance__count": 1,
    })
    _json(logs / "1_synth.json", {"synth__design__instance__count": 1})
    _json(logs / "3_5_place_dp.json", {"detailedplace__design__instance__count": 1})
    _json(logs / "4_1_cts.json", {"cts__timing__setup__ws": -28.1865})
    value = extract_metrics(work, "asap7", "aes", expected_stage="cts")
    assert value["clock_period_ns"] == pytest.approx(.380)
    assert value["stages"]["cts"]["metrics"]["setup_slack_ns"] == pytest.approx(
        -.0281865)
    assert value["stages"]["cts"]["metrics"]["fmax_mhz"] == pytest.approx(2449.86)


def test_protected_evaluator_never_writes_error_evidence_through_adapter_symlink(tmp_path):
    workspace, outside = tmp_path / "workspace", tmp_path / "outside"
    workspace.mkdir(); outside.mkdir()
    (workspace / "orfs").symlink_to(outside, target_is_directory=True)
    manifest = PluginManifest(
        plugin_id="orfs", plugin_version="1.0.0", adapter_entry=("echo",),
        capabilities=("test",), supported_arch=("test",),
        input_schema={"type": "object"}, output_schema={"type": "object"},
    )
    task = TaskSpec(
        task_id="symlink", project_id="project", design_id="design", plugin_id="orfs",
        inputs={}, parameters={"target_stage": "finish"}, timeout_seconds=1,
    )
    artifact = ORFSProtectedEvaluator().evaluate(
        manifest=manifest, task=task, workspace=str(workspace),
    )[0]
    assert artifact["path"] == "protected_evaluator_error.log"
    assert (workspace / artifact["path"]).is_file()
    assert not list(outside.rglob("*"))
