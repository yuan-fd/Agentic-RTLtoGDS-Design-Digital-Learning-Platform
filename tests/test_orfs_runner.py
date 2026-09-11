from __future__ import annotations

import hashlib
from pathlib import Path
import json
import pytest

from openroad_platform_contracts import RunRequest, RunStage, RunStatus
from openroad_platform_execution import ORFSRunner
import openroad_platform_execution.orfs_runner as runner_module


def _fake_runtime(tmp_path: Path):
    orfs = tmp_path / "orfs"
    flow = orfs / "flow"
    flow.mkdir(parents=True)
    (flow / "Makefile").write_text(
        "OUT := $(WORK_HOME)/results/nangate45/top/base\n"
        "define emit\n\n\tmkdir -p $(OUT)\n\tprintf odb > $(OUT)/$(1)\nendef\n"
        "synth:\n\t$(call emit,1_synth.odb)\n"
        "floorplan:\n\t$(call emit,2_floorplan.odb)\n"
        "place:\n\t$(call emit,3_place.odb)\n"
        "cts:\n\t$(call emit,4_cts.odb)\n"
        "route:\n\t$(call emit,5_route.odb)\n"
        "finish:\n\t$(call emit,6_final.odb)\n"
        "\tprintf def > $(OUT)/6_final.def\n"
        "\tprintf netlist > $(OUT)/6_final.v\n"
        "\tprintf gds > $(OUT)/6_final.gds\n"
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("openroad", "yosys"):
        binary = bin_dir / name
        binary.write_text("#!/bin/sh\nprintf 'fake-tool 1.0\\n'\n")
        binary.chmod(0o755)
    return orfs, bin_dir


def test_runner_executes_stages_and_applies_finish_hard_gate(tmp_path):
    orfs, bin_dir = _fake_runtime(tmp_path)
    rtl = tmp_path / "top.v"
    rtl.write_text("module top(input clk, input a, output y); assign y = a; endmodule\n")
    runner = ORFSRunner(
        orfs_root=orfs,
        work_root=tmp_path / "runs",
        openroad_bin=bin_dir / "openroad",
        yosys_bin=bin_dir / "yosys",
    )
    plan = runner.prepare(RunRequest(rtl_path=str(rtl), top="top"))
    config = Path(plan.config_path).read_text()
    assert "ABC_SPEED" not in config
    assert "ABC_POWER" not in config

    result = runner.run(plan)
    assert result.status is RunStatus.SUCCEEDED
    assert len(result.stages) == 6
    assert {artifact.kind.value for artifact in result.artifacts} >= {"odb", "def", "gds"}
    assert result.milestones == {
        "synthesizable": True,
        "functionally_verified": False,
        "implementation_valid": True,
        "gds_complete": True,
    }
    # Execution owns raw process evidence; derived analysis is a separate
    # post-processing concern and must not be created by the runner.
    assert not (Path(plan.workdir) / "analysis/report.json").exists()
    assert not (Path(plan.workdir) / "analysis/parameter_liveness.json").exists()
    assert (Path(plan.workdir) / "run_result.json").is_file()


def test_runner_bounds_orfs_parallelism_by_server_policy(tmp_path, monkeypatch):
    orfs, bin_dir = _fake_runtime(tmp_path)
    rtl = tmp_path / "top.v"
    rtl.write_text("module top; endmodule\n")
    runner = ORFSRunner(
        orfs_root=orfs, work_root=tmp_path / "runs",
        openroad_bin=bin_dir / "openroad", yosys_bin=bin_dir / "yosys",
    )
    plan = runner.prepare(RunRequest(rtl_path=str(rtl), top="top"))
    assert "NUM_CORES=16" in runner._make_command(plan, "synth")
    monkeypatch.setenv("OPENROAD_PLATFORM_ORFS_CORES", "7")
    assert "NUM_CORES=7" in runner._make_command(plan, "synth")
    monkeypatch.setenv("OPENROAD_PLATFORM_ORFS_CORES", "0")
    with pytest.raises(ValueError, match="between 1 and 64"):
        runner._make_command(plan, "synth")


def test_runner_registers_native_finish_timing_report(tmp_path):
    orfs, bin_dir = _fake_runtime(tmp_path)
    rtl = tmp_path / "top.v"
    rtl.write_text("module top; endmodule\n")
    runner = ORFSRunner(
        orfs_root=orfs, work_root=tmp_path / "runs",
        openroad_bin=bin_dir / "openroad", yosys_bin=bin_dir / "yosys",
    )
    plan = runner.prepare(RunRequest(rtl_path=str(rtl), top="top"))
    report = Path(plan.workdir) / "reports/nangate45/top/base/6_finish.rpt"
    report.parent.mkdir(parents=True)
    report.write_text("Startpoint: a\nEndpoint: y\nPath Type: max\n1.0 data arrival time\n0.2 slack (MET)\n")
    empty_drc = report.with_name("5_route_drc.rpt")
    empty_drc.write_text("")
    artifacts = runner._collect_artifacts(plan)
    timing = next(item for item in artifacts if item.path.endswith("6_finish.rpt"))
    assert timing.kind.value == "report"
    assert timing.sha256
    assert not any(item.path.endswith("5_route_drc.rpt") for item in artifacts)


def test_runner_collects_m1_metrics_only_from_nonempty_json_report_artifacts(tmp_path):
    orfs, bin_dir = _fake_runtime(tmp_path)
    rtl = tmp_path / "top.v"
    rtl.write_text("module top; endmodule\n")
    runner = ORFSRunner(orfs_root=orfs, work_root=tmp_path / "runs",
                        openroad_bin=bin_dir / "openroad", yosys_bin=bin_dir / "yosys")
    plan = runner.prepare(RunRequest(rtl_path=str(rtl), top="top"))
    logs = Path(plan.workdir) / "logs/nangate45/top/base"
    logs.mkdir(parents=True)
    (logs / "6_report.json").write_text(json.dumps({
        "finish__design__instance__area": 12.5,
        "finish__timing__setup__ws": -0.2,
    }))
    (logs / "5_2_route.json").write_text(json.dumps({
        "detailedroute__route__drc_errors": 0,
    }))
    artifacts = runner._collect_artifacts(plan)
    metrics = {item.name: item for item in runner._collect_metrics(plan)}
    assert {"6_report.json", "5_2_route.json"} <= {Path(item.path).name for item in artifacts}
    assert metrics["finish__timing__setup__ws"].source == "orfs-finish-report-json-v1"
    assert metrics["detailedroute__route__drc_errors"].source == "orfs-route-report-json-v1"


def test_runner_fails_when_process_succeeds_without_required_artifact(tmp_path):
    orfs, bin_dir = _fake_runtime(tmp_path)
    makefile = orfs / "flow/Makefile"
    makefile.write_text("synth:\n\t@true\n")
    rtl = tmp_path / "top.v"
    rtl.write_text("module top; endmodule\n")
    runner = ORFSRunner(
        orfs_root=orfs,
        work_root=tmp_path / "runs",
        openroad_bin=bin_dir / "openroad",
        yosys_bin=bin_dir / "yosys",
    )
    request = RunRequest(rtl_path=str(rtl), top="top", target_stage="synth")
    plan = runner.prepare(RunRequest.from_dict(request.to_dict()))
    result = runner.run(plan)
    assert result.status is RunStatus.FAILED
    assert "Required artifacts" in result.error
    assert (Path(plan.workdir) / "analysis/flow_error.log").is_file()


def test_paper_orfs_synth_netlist_is_a_valid_stage_artifact(tmp_path):
    orfs, bin_dir = _fake_runtime(tmp_path)
    (orfs / "flow/Makefile").write_text(
        "OUT := $(WORK_HOME)/results/nangate45/top/base\n"
        "synth:\n\tmkdir -p $(OUT)\n\tprintf netlist > $(OUT)/1_synth.v\n"
    )
    rtl = tmp_path / "top.v"; rtl.write_text("module top; endmodule\n")
    runner = ORFSRunner(
        orfs_root=orfs, work_root=tmp_path / "runs",
        openroad_bin=bin_dir / "openroad", yosys_bin=bin_dir / "yosys",
    )
    result = runner.run(runner.prepare(RunRequest(
        rtl_path=str(rtl), top="top", target_stage=RunStage.SYNTH)))
    assert result.status is RunStatus.SUCCEEDED
    assert any(Path(item.path).name == "1_synth.v" for item in result.artifacts)


def test_runner_stages_hash_bound_fastroute_recipe(tmp_path):
    orfs, bin_dir = _fake_runtime(tmp_path)
    rtl = tmp_path / "top.v"; rtl.write_text("module top; endmodule\n")
    fast_route = tmp_path / "fastroute.tcl"
    fast_route.write_text("set_global_routing_layer_adjustment met1-met5 0.4\n")
    runner = ORFSRunner(
        orfs_root=orfs, work_root=tmp_path / "runs",
        openroad_bin=bin_dir / "openroad", yosys_bin=bin_dir / "yosys",
    )
    plan = runner.prepare(RunRequest(
        rtl_path=str(rtl), top="top", target_stage=RunStage.SYNTH,
        fast_route_tcl_path=str(fast_route),
    ))
    staged = Path(plan.config_path).with_name("fastroute.tcl")
    assert staged.read_bytes() == fast_route.read_bytes()
    assert "FASTROUTE_TCL" in Path(plan.config_path).read_text()
    snapshot = json.loads((Path(plan.workdir) / "toolchain_snapshot.json").read_text())
    assert snapshot["request"]["fast_route_tcl"]["sha256"] == \
        hashlib.sha256(fast_route.read_bytes()).hexdigest()


def test_runner_backports_exact_upstream_headless_finish_fix_with_receipt(
        tmp_path, monkeypatch):
    orfs, bin_dir = _fake_runtime(tmp_path)
    scripts = orfs / "flow/scripts"; scripts.mkdir()
    original = (
        "report_metrics 6 finish\n"
        "if {[expr [llength [info procs save_image]] > 0]} {\n"
        "  gui::show save_images false\n}\n"
    )
    patched = original.replace(
        "if {[expr [llength [info procs save_image]] > 0]} {",
        "if {[ord::openroad_gui_compiled] && "
        "[llength [info commands gui::show]] > 0} {",
    )
    monkeypatch.setitem(
        runner_module._HEADLESS_FINISH_BACKPORT, "source_sha256",
        hashlib.sha256(original.encode()).hexdigest(),
    )
    monkeypatch.setitem(
        runner_module._HEADLESS_FINISH_BACKPORT, "patched_sha256",
        hashlib.sha256(patched.encode()).hexdigest(),
    )
    source = scripts / "final_report.tcl"
    source.write_text(original)
    rtl = tmp_path / "top.v"; rtl.write_text("module top; endmodule\n")
    runner = ORFSRunner(
        orfs_root=orfs, work_root=tmp_path / "runs",
        openroad_bin=bin_dir / "openroad", yosys_bin=bin_dir / "yosys",
    )
    plan = runner.prepare(RunRequest(
        rtl_path=str(rtl), top="top", target_stage=RunStage.SYNTH,
    ))
    staged = Path(plan.flow_home) / "scripts/final_report.tcl"
    assert "[llength [info commands gui::show]] > 0" in staged.read_text()
    receipt_path = Path(plan.workdir) / "flow_compatibility.json"
    receipt = json.loads(receipt_path.read_text())
    change = receipt["changes"][0]
    assert change["upstream_commit"] == \
        "e7a0725758c0abde2b69e2cdba783435238748ef"
    assert change["paired_openroad_commit"] == \
        "4630b597e7da45019e0e17f19bc58f9128bdbc03"
    assert change["source_sha256"] == hashlib.sha256(original.encode()).hexdigest()
    assert change["patched_sha256"] == hashlib.sha256(staged.read_bytes()).hexdigest()
    assert change["protected_inputs_changed"] is False
    snapshot = json.loads(
        (Path(plan.workdir) / "toolchain_snapshot.json").read_text()
    )
    assert snapshot["files"]["flow_compatibility_receipt"]["sha256"] == \
        hashlib.sha256(receipt_path.read_bytes()).hexdigest()


def test_runner_does_not_guess_a_headless_patch_for_unrecognized_source(tmp_path):
    orfs, bin_dir = _fake_runtime(tmp_path)
    scripts = orfs / "flow/scripts"; scripts.mkdir()
    original = "if {[expr [llength [info procs save_image]] > 0]} {\n# different\n"
    (scripts / "final_report.tcl").write_text(original)
    rtl = tmp_path / "top.v"; rtl.write_text("module top; endmodule\n")
    runner = ORFSRunner(
        orfs_root=orfs, work_root=tmp_path / "runs",
        openroad_bin=bin_dir / "openroad", yosys_bin=bin_dir / "yosys",
    )
    plan = runner.prepare(RunRequest(
        rtl_path=str(rtl), top="top", target_stage=RunStage.SYNTH,
    ))
    assert (Path(plan.flow_home) / "scripts/final_report.tcl").read_text() == original
    receipt = json.loads(
        (Path(plan.workdir) / "flow_compatibility.json").read_text()
    )
    assert receipt["changes"] == []


def test_finish_failure_can_export_gds_without_claiming_valid_implementation(tmp_path):
    orfs, bin_dir = _fake_runtime(tmp_path)
    (orfs / "flow/Makefile").write_text(
        "OUT := $(WORK_HOME)/results/nangate45/top/base\n"
        "synth:\n\tmkdir -p $(OUT)\n\tprintf odb > $(OUT)/1_synth.odb\n"
        "floorplan:\n\tprintf odb > $(OUT)/2_floorplan.odb\n"
        "place:\n\tprintf odb > $(OUT)/3_place.odb\n"
        "cts:\n\tprintf odb > $(OUT)/4_cts.odb\n"
        "route:\n\tprintf odb > $(OUT)/5_route.odb\n"
        "finish:\n\tprintf odb > $(OUT)/6_final.odb\n"
        "\tprintf def > $(OUT)/6_final.def\n"
        "\tprintf netlist > $(OUT)/6_final.v\n"
        "\t@false\n"
        "gds:\n\tprintf gds > $(OUT)/6_final.gds\n"
    )
    rtl = tmp_path / "top.v"
    rtl.write_text("module top; endmodule\n")
    runner = ORFSRunner(
        orfs_root=orfs,
        work_root=tmp_path / "runs",
        openroad_bin=bin_dir / "openroad",
        yosys_bin=bin_dir / "yosys",
    )
    result = runner.run(runner.prepare(RunRequest(rtl_path=str(rtl), top="top")))
    assert result.status is RunStatus.FAILED
    assert result.milestones["implementation_valid"] is False
    assert result.milestones["gds_complete"] is True
    assert "GDS export succeeded" in result.error


def test_explicit_minimum_die_area_excludes_utilization_floorplan_mode(tmp_path):
    orfs, bin_dir = _fake_runtime(tmp_path)
    rtl = tmp_path / "tiny.v"
    rtl.write_text("module tiny(input a, output y); assign y=~a; endmodule\n")
    runner = ORFSRunner(
        orfs_root=orfs, work_root=tmp_path / "runs",
        openroad_bin=bin_dir / "openroad", yosys_bin=bin_dir / "yosys",
    )
    request = RunRequest(
        rtl_path=str(rtl), top="tiny", target_stage=RunStage.SYNTH,
        minimum_die_size_um=20,
    )
    plan = runner.prepare(request)
    config = Path(plan.config_path).read_text()
    assert "DIE_AREA = 0 0 20 20" in config
    assert "CORE_AREA = 2 2 18 18" in config
    assert "CORE_UTILIZATION" not in config


def test_default_non_nangate_floorplan_has_a_complete_initialization_policy(tmp_path):
    """Regression: DIE_AREA alone leaves ORFS floorplan undefined."""
    orfs, bin_dir = _fake_runtime(tmp_path)
    rtl = tmp_path / "tiny.v"
    rtl.write_text("module tiny(input a, output y); assign y=~a; endmodule\n")
    runner = ORFSRunner(
        orfs_root=orfs, work_root=tmp_path / "runs",
        openroad_bin=bin_dir / "openroad", yosys_bin=bin_dir / "yosys",
    )
    plan = runner.prepare(RunRequest(
        rtl_path=str(rtl), top="tiny", platform="sky130hd",
        core_utilization_pct=37, target_stage=RunStage.SYNTH,
    ))
    config = Path(plan.config_path).read_text()
    assert "CORE_UTILIZATION = 37" in config
    assert "DIE_AREA" not in config


def test_orfs_random_seed_is_explicit_in_generated_config(tmp_path):
    orfs, bin_dir = _fake_runtime(tmp_path)
    rtl = tmp_path / "tiny.v"
    rtl.write_text("module tiny(input a, output y); assign y=~a; endmodule\n")
    runner = ORFSRunner(
        orfs_root=orfs, work_root=tmp_path / "runs",
        openroad_bin=bin_dir / "openroad", yosys_bin=bin_dir / "yosys",
    )
    plan = runner.prepare(RunRequest(
        rtl_path=str(rtl), top="tiny", or_seed=271828,
        target_stage=RunStage.SYNTH,
    ))
    config = Path(plan.config_path).read_text()
    assert "export OR_SEED = 271828" in config
    assert plan.request.or_seed == 271828


def test_runner_preserves_ordered_systemverilog_bundle_and_include_tree(tmp_path):
    orfs, bin_dir = _fake_runtime(tmp_path)
    root = tmp_path / "ibex"
    include = root / "vendor/prim"; include.mkdir(parents=True)
    (include / "prim_assert.svh").write_text("`define ASSERT(x)\n")
    package = root / "ibex_pkg.sv"; package.write_text("package ibex_pkg; endpackage\n")
    top = root / "ibex_core.sv"; top.write_text("module ibex_core(input clk_i); endmodule\n")
    clock_gate = root / "syn/prim_clock_gating.v"; clock_gate.parent.mkdir()
    clock_gate.write_text("module prim_clock_gating; endmodule\n")
    runner = ORFSRunner(
        orfs_root=orfs, work_root=tmp_path / "runs",
        openroad_bin=bin_dir / "openroad", yosys_bin=bin_dir / "yosys",
    )
    request = RunRequest(
        rtl_path=str(top), rtl_root=str(root),
        rtl_files=(str(package), str(top), str(clock_gate)),
        rtl_include_dirs=(str(include),), synth_hdl_frontend="slang",
        design_options={"openroad_hierarchical": True, "swap_arith_operators": 1},
        top="ibex_core", clock="clk_i", target_stage=RunStage.SYNTH,
    )
    plan = runner.prepare(RunRequest.from_dict(request.to_dict()))
    config = Path(plan.config_path).read_text()
    staged = Path(plan.workdir) / "designs/src/ibex_core"
    assert config.index(str(staged / "ibex_pkg.sv")) < config.index(str(staged / "ibex_core.sv"))
    assert "export SYNTH_HDL_FRONTEND = slang" in config
    assert "export OPENROAD_HIERARCHICAL = 1" in config
    assert "export SWAP_ARITH_OPERATORS = 1" in config
    assert str(staged / "vendor/prim") in config
    assert (staged / "vendor/prim/prim_assert.svh").is_file()
    contract = json.loads((Path(plan.workdir) / "design_input_manifest.json").read_text())
    assert contract["source_order"] == [
        "ibex_pkg.sv", "ibex_core.sv", "syn/prim_clock_gating.v",
    ]


def test_runner_records_typed_parameter_contract_before_execution(tmp_path):
    orfs, bin_dir = _fake_runtime(tmp_path)
    rtl = tmp_path / "top.v"; rtl.write_text("module top; endmodule\n")
    runner = ORFSRunner(orfs_root=orfs, work_root=tmp_path / "runs",
                        openroad_bin=bin_dir / "openroad", yosys_bin=bin_dir / "yosys")
    plan = runner.prepare(RunRequest(
        rtl_path=str(rtl), top="top", platform="asap7",
        flow_parameters={"core_utilization_pct": 55, "enable_dpo": True},
    ))
    contract = json.loads((Path(plan.workdir) / "parameter_contract.json").read_text())
    assert contract["requested_parameters"] == {
        "core_utilization_pct": 55, "enable_dpo": 1,
    }
    assert contract["effective_configuration_id"].startswith("orfs-effective-")
    assert contract["claim_boundary"].startswith("requested and materialized")


def test_finish_json_fallback_preserves_terminal_qor_without_analysis_package(tmp_path):
    orfs, bin_dir = _fake_runtime(tmp_path)
    rtl = tmp_path / "top.v"; rtl.write_text("module top; endmodule\n")
    runner = ORFSRunner(orfs_root=orfs, work_root=tmp_path / "runs",
                        openroad_bin=bin_dir / "openroad", yosys_bin=bin_dir / "yosys")
    plan = runner.prepare(RunRequest(rtl_path=str(rtl), top="top"))
    report = Path(plan.workdir) / "logs/nangate45/top/base/6_report.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({"finish__design__instance__area": 12.5,
                                  "finish__timing__setup__ws": 0.2,
                                  "finish__power__total": 0.004}), encoding="utf-8")
    values = {metric.name: metric.value for metric in runner._collect_finish_metrics_fallback(plan)}
    assert values == {"finish__design__instance__area": 12.5,
                      "finish__timing__setup__ws": 0.2,
                      "finish__power__total": 0.004}
