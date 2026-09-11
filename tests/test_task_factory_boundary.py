from __future__ import annotations

import pytest

from openroad_platform_contracts import RTLToGDSRequest
from openroad_platform_execution import ORFSRTLToGDSFactory, build_orfs_task


def test_orfs_factory_preserves_frozen_builder_fields(tmp_path):
    rtl = tmp_path / "top.v"
    rtl.write_text("module top(input a, output y); assign y = a; endmodule\n", encoding="utf-8")
    options = {
        "platform_name": "nangate45", "target_stage": "finish",
        "clock_period_ns": 8.0, "core_utilization_pct": 35.0,
        "place_density": 0.55, "or_seed": 123,
        "stage_timeout_seconds": 77, "timeout_seconds": 88,
    }
    expected = build_orfs_task(
        rtl, project_id="p1", design_id="top", top="top", task_id="frozen-task",
        labels={"source": "fixture"}, **options,
    )
    actual = ORFSRTLToGDSFactory().build(RTLToGDSRequest(
        rtl_path=str(rtl), project_id="p1", design_id="top", top="top",
        task_id="frozen-task", labels={"source": "fixture"}, options=options,
    ))
    assert actual.to_dict() == expected.to_dict()


def test_orfs_factory_preserves_operator_owned_reference_bundle(tmp_path):
    root = tmp_path / "rtl"; root.mkdir()
    rtl = root / "top.v"; rtl.write_text("module top(input clk); endmodule\n")
    helper = root / "helper.v"; helper.write_text("module helper; endmodule\n")
    sdc = tmp_path / "constraint.sdc"
    sdc.write_text("create_clock -period 4.5 [get_ports clk]\n")
    fast_route = tmp_path / "fastroute.tcl"
    fast_route.write_text("set_global_routing_layer_adjustment met1-met5 0.4\n")
    options = {
        "clock": "clk", "platform_name": "sky130hd",
        "target_stage": "finish", "clock_period_ns": 4.5,
        "core_utilization_pct": 20, "place_density": .6,
        "flow_parameters": {"tns_end_percent": 100},
        "rtl_files": (rtl, helper), "rtl_root": root,
        "rtl_include_dirs": (), "synth_hdl_frontend": None,
        "design_options": {"remove_abc_buffers": 1}, "sdc_path": sdc,
        "fast_route_tcl_path": fast_route,
    }
    expected = build_orfs_task(
        rtl, project_id="p1", design_id="aes", top="top", **options,
    )
    actual = ORFSRTLToGDSFactory().build(RTLToGDSRequest(
        rtl_path=str(rtl), project_id="p1", design_id="aes", top="top",
        task_id=expected.task_id, options=options,
    ))
    assert actual.to_dict() == expected.to_dict()
    assert len(actual.inputs["rtl_bundle"]["files"]) == 2
    assert actual.inputs["sdc"]["sha256"]
    assert actual.inputs["fast_route_tcl"]["sha256"]


def test_orfs_factory_rejects_unknown_options_and_invalid_task(tmp_path):
    rtl = tmp_path / "top.v"; rtl.write_text("module top; endmodule\n", encoding="utf-8")
    factory = ORFSRTLToGDSFactory()
    with pytest.raises(ValueError, match="Unsupported ORFS task options"):
        factory.build(RTLToGDSRequest(
            rtl_path=str(rtl), project_id="p1", design_id="top",
            options={"shell": "bad"},
        ))
    with pytest.raises(ValueError, match="Unsupported capability"):
        factory.build(RTLToGDSRequest(
            rtl_path=str(rtl), project_id="p1", design_id="top",
            capability="eda.not-admitted",
        ))


def test_orfs_factory_reconfiguration_keeps_the_allowlist_below_scheduler(tmp_path):
    rtl = tmp_path / "top.v"; rtl.write_text("module top; endmodule\n", encoding="utf-8")
    factory = ORFSRTLToGDSFactory()
    task = factory.build(RTLToGDSRequest(
        rtl_path=str(rtl), project_id="p1", design_id="top",
    ))
    changed = factory.reconfigure(task, {"core_utilization_pct": 20.0})
    assert changed.parameters["core_utilization_pct"] == 20.0
    with pytest.raises(ValueError):
        factory.reconfigure(task, {"shell": "bad"})


def test_synth_task_requires_netlist_while_finish_requires_physical_outputs(tmp_path):
    rtl = tmp_path / "top.v"; rtl.write_text("module top; endmodule\n")
    synth = ORFSRTLToGDSFactory().build(RTLToGDSRequest(
        rtl_path=str(rtl), project_id="p1", design_id="top",
        options={"target_stage": "synth"},
    ))
    finish = ORFSRTLToGDSFactory().build(RTLToGDSRequest(
        rtl_path=str(rtl), project_id="p1", design_id="top",
        options={"target_stage": "finish"},
    ))
    assert "netlist" in synth.expected_artifacts and "odb" not in synth.expected_artifacts
    assert {"odb", "def", "netlist", "gds"} <= set(finish.expected_artifacts)
