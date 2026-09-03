from __future__ import annotations

import hashlib
import json
from pathlib import Path

from openroad_platform_execution import (
    ORFSReferenceDesign, generated_design_from_platform_plan,
    generated_design_from_reference_design, install_generated_design_adapter,
    validate_generated_design_adapter,
)
import pytest


def _orfs(tmp_path: Path) -> Path:
    root = tmp_path / "orfs"
    (root / "flow").mkdir(parents=True)
    (root / "flow/Makefile").write_text("all:\n\t@true\n", encoding="utf-8")
    return root


def test_generated_adapter_pins_ordered_rtl_and_sdc_bytes(tmp_path):
    orfs = _orfs(tmp_path)
    rtl_a = tmp_path / "pkg.sv"; rtl_a.write_text("package p; endpackage\n")
    rtl_b = tmp_path / "top.sv"; rtl_b.write_text("module top(input clk); endmodule\n")
    include = tmp_path / "include"; include.mkdir()
    (include / "defs.svh").write_text("`define WIDTH 8\n")
    sdc = tmp_path / "constraint.sdc"; sdc.write_text("create_clock -period 10 [get_ports clk]\n")
    manifest = install_generated_design_adapter(
        orfs_root=orfs, platform="nangate45", top="top",
        rtl_files={"pkg.sv": rtl_a, "rtl/top.sv": rtl_b}, sdc_path=sdc,
        clock_period_ns=10, core_utilization_pct=50, place_density=.55,
        or_seed=101, flow_parameters={}, source_identity={"run_id": "run-1"},
        rtl_include_dirs={"include": include}, synth_hdl_frontend="slang",
    )
    root = Path(manifest["adapter_root"])
    assert manifest["schema_version"] == 3
    assert manifest["configuration_policy_version"] == \
        "exclusive-placement-density-v1"
    assert [item["relative_path"] for item in manifest["rtl_sources"]] == [
        "pkg.sv", "rtl/top.sv",
    ]
    assert hashlib.sha256((root / "src/pkg.sv").read_bytes()).hexdigest() == \
        manifest["rtl_sources"][0]["sha256"]
    config = (root / "config.mk").read_text()
    assert f"export DESIGN_NAME = top" in config
    assert f"export DESIGN_NICKNAME = {manifest['namespace']}" in config
    assert str(root / "src/pkg.sv") in config
    assert str(root / "src/rtl/top.sv") in config
    assert str(root / "constraint.sdc") in config
    assert str(root / "src/include") in config
    assert "SYNTH_HDL_FRONTEND = slang" in config
    assert (root / "src/include/defs.svh").is_file()
    assert install_generated_design_adapter(
        orfs_root=orfs, platform="nangate45", top="top",
        rtl_files={"pkg.sv": rtl_a, "rtl/top.sv": rtl_b}, sdc_path=sdc,
        clock_period_ns=10, core_utilization_pct=50, place_density=.55,
        or_seed=101, flow_parameters={}, source_identity={"run_id": "run-1"},
        rtl_include_dirs={"include": include}, synth_hdl_frontend="slang",
    ) == manifest
    assert validate_generated_design_adapter(
        root, orfs_root=orfs)["identity_sha256"] == manifest["identity_sha256"]


def test_generated_adapter_integrity_gate_rejects_tampering(tmp_path):
    orfs = _orfs(tmp_path)
    rtl = tmp_path / "top.v"; rtl.write_text("module top; endmodule\n")
    sdc = tmp_path / "constraint.sdc"; sdc.write_text("set_units -time ns\n")
    manifest = install_generated_design_adapter(
        orfs_root=orfs, platform="nangate45", top="top",
        rtl_files={"top.v": rtl}, sdc_path=sdc, clock_period_ns=10,
        core_utilization_pct=50, place_density=.55, or_seed=101,
        flow_parameters={}, source_identity={"run_id": "tamper-test"},
    )
    adapter = Path(manifest["adapter_root"])
    (adapter / "config.mk").write_text("malicious override\n")
    with pytest.raises(ValueError, match="config or SDC integrity"):
        validate_generated_design_adapter(adapter, orfs_root=orfs)


def test_platform_plan_adapter_uses_runner_copies_not_original_path(tmp_path):
    orfs = _orfs(tmp_path)
    work = tmp_path / "run"
    source = work / "designs/src/gcd/gcd.v"; source.parent.mkdir(parents=True)
    source.write_text("module gcd(input clk); endmodule\n")
    sdc = work / "designs/nangate45/gcd/constraint.sdc"; sdc.parent.mkdir(parents=True)
    sdc.write_text("create_clock -period 10 [get_ports clk]\n")
    plan = {
        "schema_version": 1, "run_id": "run-1", "design": "gcd",
        "workdir": str(work),
        "request": {
            "platform": "nangate45", "clock_period_ns": 10,
            "core_utilization_pct": 50, "place_density": .55,
            "or_seed": 101, "flow_parameters": {},
        },
    }
    plan_path = work / "plan.json"; plan_path.write_text(json.dumps(plan))
    manifest = generated_design_from_platform_plan(plan_path, orfs_root=orfs)
    assert manifest["source_identity"]["run_id"] == "run-1"
    assert manifest["rtl_sources"][0]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert manifest["sdc_sha256"] == hashlib.sha256(sdc.read_bytes()).hexdigest()


def test_reference_adapter_executes_exact_logical_bundle_and_sdc(tmp_path):
    orfs = _orfs(tmp_path)
    source_root = tmp_path / "ibex_sv"; source_root.mkdir()
    top = source_root / "ibex_core.sv"
    top.write_text("module ibex_core(input clk_i); endmodule\n")
    extra = source_root / "syn/rtl/prim_clock_gating.v"
    extra.parent.mkdir(parents=True)
    extra.write_text("module prim_clock_gating; endmodule\n")
    include = source_root / "vendor/lowrisc_ip/prim/rtl"; include.mkdir(parents=True)
    (include / "prim_assert.sv").write_text("`define ASSERT(x)\n")
    sdc = tmp_path / "constraint_pos_slack.sdc"
    sdc.write_text("create_clock -period 1468 [get_ports clk_i]\n")
    reference = ORFSReferenceDesign(
        platform="asap7", design="ibex", top="ibex_core", clock="clk_i",
        clock_period_ns=1.468, rtl_root=source_root,
        rtl_files=(top, extra), include_dirs=(include,), sdc_path=sdc,
        synth_hdl_frontend="slang",
        design_options={"openroad_hierarchical": 1},
        native_baseline_overrides={
            "core_utilization_pct": 40, "place_density_lb_addon": .2,
            "enable_dpo": 0, "tns_end_percent": 100,
        },
        source_fingerprint="a" * 64, orfs_commit="b" * 40,
    )
    manifest = generated_design_from_reference_design(
        reference, orfs_root=orfs,
        flow_parameters={
            "core_utilization_pct": 40, "place_density": .55,
            "enable_dpo": False, "tns_end_percent": 100,
        },
        or_seed=101, autotuner_initial_points=({"CORE_UTILIZATION": 40},),
    )
    adapter = Path(manifest["adapter_root"])
    assert manifest["logical_design"] == "ibex"
    assert manifest["comparison_identity_sha256"] == "a" * 64
    assert manifest["namespace"] != "ibex"
    assert manifest["sdc_sha256"] == hashlib.sha256(sdc.read_bytes()).hexdigest()
    assert hashlib.sha256((adapter / "constraint.sdc").read_bytes()).hexdigest() == \
        hashlib.sha256(sdc.read_bytes()).hexdigest()
    config = (adapter / "config.mk").read_text(encoding="utf-8")
    assert f"SDC_FILE = {adapter / 'constraint.sdc'}" in config
    assert "SYNTH_HDL_FRONTEND = slang" in config
    assert "OPENROAD_HIERARCHICAL = 1" in config
    assert str(adapter / "src/syn/rtl/prim_clock_gating.v") in config


def test_generated_adapter_emits_only_one_placement_density_policy(tmp_path):
    orfs = _orfs(tmp_path)
    rtl = tmp_path / "top.v"; rtl.write_text("module top; endmodule\n")
    sdc = tmp_path / "constraint.sdc"; sdc.write_text("set_units -time ns\n")
    addon = install_generated_design_adapter(
        orfs_root=orfs, platform="asap7", top="top", rtl_files={"top.v": rtl},
        sdc_path=sdc, clock_period_ns=1, core_utilization_pct=40,
        place_density=.55, or_seed=101,
        flow_parameters={"place_density_lb_addon": .2},
        source_identity={"case": "addon"})
    addon_config = (Path(addon["adapter_root"]) / "config.mk").read_text()
    assert "export PLACE_DENSITY_LB_ADDON = 0.2" in addon_config
    assert "export PLACE_DENSITY =" not in addon_config

    direct = install_generated_design_adapter(
        orfs_root=orfs, platform="asap7", top="top", rtl_files={"top.v": rtl},
        sdc_path=sdc, clock_period_ns=1, core_utilization_pct=40,
        place_density=.55, or_seed=101, flow_parameters={},
        source_identity={"case": "direct"})
    direct_config = (Path(direct["adapter_root"]) / "config.mk").read_text()
    assert "export PLACE_DENSITY = 0.55" in direct_config
    assert "PLACE_DENSITY_LB_ADDON" not in direct_config
