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


def test_protected_evaluator_separates_full_candidate_signoff_from_upstream_objective(tmp_path):
    workspace = tmp_path / "candidate-workspace"
    logs = workspace / "work/logs/sky130hd/aes/candidate"
    results = workspace / "work/results/sky130hd/aes/candidate"
    logs.mkdir(parents=True); results.mkdir(parents=True)
    for prefix in ("1_synth", "2_1_floorplan", "3_5_place_dp", "4_1_cts"):
        payload = {"design__instance__count": 1}
        if prefix == "2_1_floorplan":
            payload["run__flow__platform__time_units"] = "1ns"
        _json(logs / f"{prefix}.json", payload)
    _json(logs / "5_2_route.json", {
        "detailedroute__design__instance__count": 1,
        "detailedroute__route__drc_errors": 0,
    })
    _json(logs / "6_report.json", {
        "finish__design__instance__area": 123.0,
        "finish__design__die__area": 456.0,
        "finish__timing__setup__ws": 0.15,
        "finish__power__total": 0.25,
    })
    for name in ("6_final.odb", "6_final.def", "6_final.gds", "6_final.v"):
        (results / name).write_bytes(name.encode())
    config = workspace / "mapped_config.mk"
    config.write_text("export CLK_PERIOD = 4.5\n", encoding="utf-8")
    candidate = {
        "CLK": 4.5, "UTIL": 20, "TNS_End_Percent": 100,
        "GP_PAD": 0, "DP_PAD": 1, "DPO": 1, "PIN_ADJ": .3,
        "UP_ADJ": .4, "LB_ADDON": .2, "HIER_SYNTH": 0,
        "CTS_CSIZE": 10, "CTS_CDIA": 80,
    }
    _json(workspace / "candidate_metrics.json", {
        "schema_version": 1, "ECP_final": 4.35,
        "raw_final_report": {"finish__timing__setup__ws": .15},
        "candidate_clock_units": "ns",
    })
    _json(workspace / "candidate_materialization.json", {
        "kind": "orfs-agent-paper-candidate-materialization",
        "platform": "sky130hd", "design": "aes", "candidate": candidate,
        "or_seed": 101, "private_config": str(config),
        "expected_report_directory": str(logs),
        "expected_result_directory": str(results),
    })
    protocol = {
        "design_bundle_sha256": "1" * 64,
        "pdk_bundle_sha256": "2" * 64,
        "toolchain_receipt_sha256": "3" * 64,
    }
    task = TaskSpec(
        task_id="full-candidate-evaluation", project_id="paper", design_id="aes",
        plugin_id="orfs-agent",
        inputs={"mode": "upstream_full_candidate", "design": "aes",
                "platform": "sky130hd", "objective": "ECP", "candidate": candidate,
                "parameter_domain": {"protocol_sha256": "4" * 64,
                                     "experiment_protocol": protocol}},
        parameters={"or_seed": 101}, timeout_seconds=1,
    )
    manifest = PluginManifest(
        plugin_id="orfs-agent", plugin_version="2025.1", adapter_entry=("echo",),
        capabilities=("optimizer.l2.upstream-full-candidate",),
        supported_arch=("test",), input_schema={"type": "object"},
        output_schema={"type": "object"},
    )
    artifact = ORFSProtectedEvaluator().evaluate(
        manifest=manifest, task=task, workspace=str(workspace),
    )[0]
    assert artifact["metadata"]["official_qor"] is True
    assert artifact["metadata"]["fixed_sdc_fair_comparison"] is False
    assert artifact["metadata"]["qor_semantics"] == "candidate-variable-clock-signoff"
    assert artifact["metadata"]["canonical_metrics"]["setup_wns_ns"] == .15
    assert "ECP_final" not in artifact["metadata"]["canonical_metrics"]
    evaluation = json.loads((workspace / artifact["path"]).read_text())
    assert evaluation["run_metadata"]["upstream_variable_clock_metrics"]["ECP_final"] == 4.35
    assert evaluation["run_metadata"]["upstream_metrics_are_canonical_signoff"] is False
    assert evaluation["identity"]["source_kind"] == "orfs-agent-upstream-variable-clock-candidate"
