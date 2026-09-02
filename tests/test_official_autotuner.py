from pathlib import Path

import pytest

from openroad_platform_analysis.official_autotuner import (
    OfficialAutoTunerInvocation, _parameter_entry, build_fair_autotuner_config,
)


def _profile():
    return {
        "platform": "nangate45",
        "frozen_constraints": ["clock_period_ns", "clock_uncertainty", "io_delay"],
        "parameter_space": [
            {"name": "core_utilization_pct", "kind": "int", "lower": 20,
             "upper": 70, "step": 1, "choices": [], "stage": "floorplan"},
            {"name": "enable_dpo", "kind": "bool", "lower": None,
             "upper": None, "step": None, "choices": [0, 1], "stage": "place"},
        ],
        "parameter_calibration": {
            "protocol": "single-knob-low-mid-high-three-paired-seeds-v1",
            "evaluation_count": 270,
            "search_eligible": ["core_utilization_pct", "enable_dpo"],
        },
    }


def test_fair_config_has_only_calibrated_knobs_and_fixed_seed():
    config, manifest = build_fair_autotuner_config(
        _profile(), or_seed=307, domain_id="test-common-v1",
        env_names={"core_utilization_pct": "CORE_UTILIZATION",
                   "enable_dpo": "ENABLE_DPO"})
    assert config == {
        "CORE_UTILIZATION": {"type": "int", "minmax": [20, 71], "step": 1},
        "ENABLE_DPO": {"type": "int", "minmax": [0, 2], "step": 1},
    }
    assert manifest["fixed_implementation_seed"] == 307
    assert manifest["domain_id"] == "test-common-v1"
    assert manifest["selected_parameter_names"] == [
        "core_utilization_pct", "enable_dpo"]
    assert len(manifest["parameter_domain_fingerprint"]) == 64
    assert not any("SDC" in key or "CLK" in key for key in config)
    assert manifest["fixed_flow_environment"] == {"OR_SEED": 307, "LEC_CHECK": 0}


def test_quantized_platform_and_upstream_value_sets_are_identical():
    integer = _parameter_entry({
        "kind": "int", "lower": 30, "upper": 75, "step": 1,
    }, "CORE_UTILIZATION")
    floating = _parameter_entry({
        "kind": "float", "lower": 0.0, "upper": 0.5, "step": 0.01,
    }, "PLACE_DENSITY_LB_ADDON")
    boolean = _parameter_entry({
        "kind": "bool", "choices": (0, 1),
    }, "ENABLE_DPO")
    assert list(range(*integer["minmax"], integer["step"])) == list(range(30, 76))
    float_values = [round(floating["minmax"][0] + i * floating["step"], 2)
                    for i in range(51)]
    upstream_float_values = []
    value = floating["minmax"][0]
    while value < floating["minmax"][1] - 1e-12:
        upstream_float_values.append(round(value, 2)); value += floating["step"]
    assert upstream_float_values == float_values
    assert list(range(*boolean["minmax"], boolean["step"])) == [0, 1]


def test_fair_config_uses_official_common_intersection_and_fixes_other_knobs():
    config, manifest = build_fair_autotuner_config(
        {**_profile(), "baseline": {"core_utilization_pct": 55, "enable_dpo": 1}},
        or_seed=101, domain_id="test-common-v1",
        env_names={"core_utilization_pct": "CORE_UTILIZATION",
                   "enable_dpo": "ENABLE_DPO"},
        supported_env_names={"CORE_UTILIZATION"})
    assert set(config) == {"CORE_UTILIZATION"}
    assert manifest["fixed_flow_environment"] == {
        "OR_SEED": 101, "LEC_CHECK": 0, "ENABLE_DPO": 1,
    }
    assert manifest["excluded_from_official_search"][0]["fixed_value"] == 1


def test_fair_config_materializes_subtractive_domain_fixed_parameters():
    profile = _profile()
    profile["parameter_space"] = profile["parameter_space"][:1]
    profile["parameter_calibration"]["search_eligible"] = ["core_utilization_pct"]
    profile["fixed_parameters"] = {"enable_dpo": 1}
    config, manifest = build_fair_autotuner_config(
        profile, or_seed=101, domain_id="test-common-v1",
        env_names={"core_utilization_pct": "CORE_UTILIZATION",
                   "enable_dpo": "ENABLE_DPO"})
    assert set(config) == {"CORE_UTILIZATION"}
    assert manifest["fixed_flow_environment"]["ENABLE_DPO"] == 1
    assert manifest["excluded_from_official_search"][0]["reason"] == \
        "fixed_by_subtractive_common_domain"


def test_fair_config_rejects_uncalibrated_or_constraint_knob():
    profile = _profile()
    profile["parameter_calibration"]["search_eligible"] = ["core_utilization_pct"]
    with pytest.raises(ValueError, match="filtered"):
        build_fair_autotuner_config(profile, or_seed=1, domain_id="test-common-v1",
                                    env_names={"core_utilization_pct": "CORE_UTILIZATION"})
    with pytest.raises(ValueError, match="constraint-changing"):
        build_fair_autotuner_config(
            _profile(), or_seed=1, domain_id="test-common-v1",
            env_names={"core_utilization_pct": "_SDC_CLK_PERIOD",
                       "enable_dpo": "ENABLE_DPO"})


def test_invocation_omits_broken_work_dir_and_uses_controlled_toolchain(tmp_path: Path):
    python = tmp_path / "python"; python.write_text("#!x"); python.chmod(0o755)
    openroad = tmp_path / "openroad"; openroad.write_text("#!x"); openroad.chmod(0o755)
    yosys = tmp_path / "yosys"; yosys.write_text("#!x"); yosys.chmod(0o755)
    autotuner = tmp_path / "AutoTuner"; autotuner.mkdir()
    orfs = tmp_path / "orfs"; (orfs / "flow").mkdir(parents=True)
    config = tmp_path / "fair.json"; config.write_text("{}")
    invocation = OfficialAutoTunerInvocation(
        python=str(python), autotuner_root=str(autotuner), orfs_root=str(orfs),
        design="gcd", platform="nangate45", config_path=str(config),
        experiment="fair-smoke", algorithm="hyperopt", samples=4,
        optimizer_seed=101, jobs=2, openroad_threads=2)
    assert "--work-dir" not in invocation.command()
    assert invocation.command()[0] == str(python.absolute())
    environment = invocation.controlled_environment(
        openroad_wrapper=str(openroad), yosys_wrapper=str(yosys),
        fixed_flow_environment={"OR_SEED": 101, "ENABLE_DPO": 1})
    manifest = invocation.manifest(environment=environment, upstream_commit="abc")
    assert manifest["cwd"] == str(orfs / "flow")
    assert manifest["work_dir_omitted"] is True
    assert manifest["environment"]["FLOW_HOME"] == str(orfs / "flow")
    assert manifest["environment"]["DESIGN_HOME"] == str(orfs / "flow/designs")
    assert manifest["environment"]["PLATFORM_HOME"] == str(orfs / "flow/platforms")
    assert manifest["environment"]["UTILS_DIR"] == str(orfs / "flow/util")
    assert manifest["environment"]["SCRIPTS_DIR"] == str(orfs / "flow/scripts")
    assert manifest["environment"]["TEST_DIR"] == str(orfs / "flow/test")
    assert manifest["environment"]["OPENROAD_EXE"] == str(openroad)
    assert manifest["environment"]["OR_SEED"] == "101"
    assert manifest["native_design_substitution"] is True
    generated = invocation.manifest(
        environment=environment, generated_design={"identity_sha256": "a" * 64})
    assert generated["native_design_substitution"] is False
    resumed = OfficialAutoTunerInvocation(
        **{**invocation.__dict__, "resume": True})
    assert resumed.command()[resumed.command().index("tune") + 1] == "--resume"
