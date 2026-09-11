from __future__ import annotations

import platform
import sys
from pathlib import Path
from types import SimpleNamespace

from apps.l1_workbench import service as workbench_service
from openroad_platform_analysis import ORFSProtectedEvaluator
from openroad_platform_contracts import PluginManifest
from openroad_platform_execution import ORFSReferenceDesign


def test_real_orfs_workbench_composes_runtime_with_protected_evaluator(tmp_path, monkeypatch):
    rtl = tmp_path / "top.v"
    rtl.write_text("module top; endmodule\n", encoding="utf-8")
    toolchain = SimpleNamespace(name="admitted-test-toolchain", validate=lambda: None)
    monkeypatch.setattr(
        workbench_service.ToolchainConfig, "from_environment",
        classmethod(lambda cls, **_kwargs: toolchain),
    )
    manifest = PluginManifest(
        plugin_id="orfs", plugin_version="1.0.0",
        adapter_entry=(sys.executable, str(tmp_path / "unused.py")),
        capabilities=("eda.rtl_to_gds",), supported_arch=(platform.machine(),),
        input_schema={"type": "object"}, output_schema={"type": "object"},
    )
    monkeypatch.setattr(workbench_service, "orfs_plugin_manifest",
                        lambda *_args, **_kwargs: manifest)

    service = workbench_service.WorkbenchService(
        tmp_path / "state", backend="orfs", rtl=rtl, top="top",
    )

    assert isinstance(service.runtime.protected_evaluator, ORFSProtectedEvaluator)


def test_managed_paper_reference_binds_full_bundle_sdc_and_baseline(tmp_path, monkeypatch):
    paper = tmp_path / "paper-orfs"
    source = paper / "flow/designs/src/aes"; source.mkdir(parents=True)
    top = source / "aes_cipher_top.v"; top.write_text("module aes_cipher_top(input clk); endmodule\n")
    helper = source / "aes_sbox.v"; helper.write_text("module aes_sbox; endmodule\n")
    sdc = paper / "flow/designs/sky130hd/aes/constraint.sdc"
    sdc.parent.mkdir(parents=True)
    sdc.write_text("create_clock -period 4.5 [get_ports clk]\n")
    fast_route = sdc.parent / "fastroute.tcl"
    fast_route.write_text("set_global_routing_layer_adjustment met1-met5 0.4\n")
    reference = ORFSReferenceDesign(
        platform="sky130hd", design="aes", top="aes_cipher_top", clock="clk",
        clock_period_ns=4.5, rtl_root=source, rtl_files=(top, helper),
        include_dirs=(), sdc_path=sdc, synth_hdl_frontend=None,
        design_options={"remove_abc_buffers": 1},
        native_baseline_overrides={"core_utilization_pct": 20,
                                   "place_density": .6,
                                   "tns_end_percent": 100},
        source_fingerprint="c" * 64,
        orfs_commit="ce8d36a7fef0ab9c47d183bcf078bce0f60f5a54",
        fast_route_tcl_path=fast_route,
    )
    monkeypatch.setattr(workbench_service, "load_orfs_agent_paper_reference_design",
                        lambda *_args, **_kwargs: reference)
    monkeypatch.setattr(workbench_service.ToolchainConfig, "validate", lambda _self: None)
    manifest = PluginManifest(
        plugin_id="orfs", plugin_version="1.0.0",
        adapter_entry=(sys.executable, str(tmp_path / "unused.py")),
        capabilities=("eda.rtl_to_gds",), supported_arch=(platform.machine(),),
        input_schema={"type": "object"}, output_schema={"type": "object"},
    )
    monkeypatch.setattr(workbench_service, "orfs_plugin_manifest",
                        lambda *_args, **_kwargs: manifest)
    binary = tmp_path / "tool"; binary.write_text("unused\n")
    service = workbench_service.WorkbenchService(
        tmp_path / "state", backend="orfs",
        managed_reference="orfs-agent-paper-aes-sky130hd",
        orfs_agent_paper_orfs=paper,
        orfs_agent_openroad_bin=binary,
        orfs_agent_yosys_bin=binary,
    )
    goal = SimpleNamespace(
        project_id="l1-workbench", design_id="aes",
        allowed_stages=("synth", "floorplan", "place", "cts", "route", "finish"),
    )
    bridge = service._bridge(goal)
    task = bridge._base_task
    assert service.top == "aes_cipher_top"
    assert service.clock_period_ns == 4.5
    assert service.policy().rtl_artifact.sha256 == "c" * 64
    assert task.inputs["clock"] == "clk"
    assert len(task.inputs["rtl_bundle"]["files"]) == 2
    assert task.inputs["sdc"]["sha256"]
    assert task.inputs["fast_route_tcl"]["sha256"]
    assert task.parameters["core_utilization_pct"] == 20
    assert task.parameters["place_density"] == .6
    assert task.parameters["flow_parameters"] == {"tns_end_percent": 100}
    assert task.parameters["design_options"] == {"remove_abc_buffers": 1}
    assert task.labels["design_bundle_sha256"] == "c" * 64
