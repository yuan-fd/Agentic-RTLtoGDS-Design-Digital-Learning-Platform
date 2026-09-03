#!/usr/bin/env python3
"""Execute one unmodified ORFS-Agent paper-style candidate in Runtime isolation.

This is deliberately an *execution* adapter, not a local optimiser.  Candidate
selection remains the pinned upstream ORFS-Agent analyst + scikit-optimize
GP/EI implementation.  The adapter implements the boundary used by upstream
``run_or_job.sh``: a 12-field candidate becomes its original environment
variables and an isolated ``make tunereport`` invocation.

The original launcher assumes a shared ORFS checkout, hard-coded SSH hosts and
one mutable results tree.  Runtime cannot use that safely.  Here each attempt
gets a private copy of the pinned paper flow and private AutoTuner configs;
neither upstream checkout is modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


PARAMETERS = (
    "CLK", "UTIL", "TNS_End_Percent", "GP_PAD", "DP_PAD", "DPO",
    "PIN_ADJ", "UP_ADJ", "LB_ADDON", "HIER_SYNTH", "CTS_CSIZE", "CTS_CDIA",
)
SUPPORTED_PLATFORMS = {"asap7", "sky130hd"}
SUPPORTED_DESIGNS = {"aes", "ibex", "jpeg"}
CANDIDATE_ENVIRONMENT_VARIABLES = (
    "CLK_PERIOD", "ABC_CLOCK_PERIOD_IN_PS", "CORE_UTILIZATION",
    "CORE_ASPECT_RATIO", "PLACE_DENSITY_LB_ADDON", "TNS_END_PERCENT",
    "RECOVER_POWER", "SYNTH_HIERARCHICAL",
    "CELL_PAD_IN_SITES_GLOBAL_PLACEMENT", "CELL_PAD_IN_SITES_DETAIL_PLACEMENT",
    "ENABLE_DPO", "GPL_TIMING_DRIVEN", "GPL_ROUTABILITY_DRIVEN",
    "CTS_CLUSTER_SIZE", "CTS_CLUSTER_DIAMETER", "PIN_LAYER_ADJUST",
    "UP_LAYER_ADJUST", "FASTROUTE_TCL", "IO_PLACER_H", "IO_PLACER_V", "CTS_ARGS",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _required_path(variable: str) -> Path:
    raw = os.environ.get(variable)
    if not raw:
        raise ValueError(f"{variable} is required in the admitted plugin environment")
    path = Path(raw).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"{variable} does not exist: {path}")
    return path


def _check_clean_git(root: Path, expected_commit: str, label: str) -> dict[str, str]:
    actual = subprocess.check_output(("git", "-C", str(root), "rev-parse", "HEAD"), text=True).strip()
    if actual != expected_commit:
        raise ValueError(f"{label} commit mismatch: {actual} != {expected_commit}")
    if subprocess.run(("git", "-C", str(root), "symbolic-ref", "-q", "HEAD"),
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        raise ValueError(f"{label} source must be detached")
    status = subprocess.check_output(
        ("git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"), text=True
    ).strip()
    if status:
        raise ValueError(f"{label} source tree is not clean")
    return {"path": str(root), "commit": actual}


def _number(candidate: Mapping[str, Any], name: str, *, integer: bool = False) -> int | float:
    value = candidate.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"candidate {name} must be numeric")
    numeric = int(value) if integer else float(value)
    if integer and float(value) != numeric:
        raise ValueError(f"candidate {name} must be an integer")
    return numeric


def validate_candidate(candidate: Mapping[str, Any], *, platform: str) -> dict[str, int | float]:
    """Validate only the upstream published 12-dimensional domain.

    No platform-only feasibility projection is applied.  In particular, this
    reproduction protocol intentionally permits candidate-specific clock and
    does not inject the historical ``DP_PAD <= GP_PAD`` restriction.
    """
    if set(candidate) != set(PARAMETERS):
        missing = sorted(set(PARAMETERS) - set(candidate))
        extra = sorted(set(candidate) - set(PARAMETERS))
        raise ValueError(f"candidate must contain exactly the upstream 12 fields; missing={missing}, extra={extra}")
    clk_low, clk_high = ((100.0, 10000.0) if platform == "asap7" else (0.5, 15.0))
    value = {
        "CLK": _number(candidate, "CLK"),
        "UTIL": _number(candidate, "UTIL", integer=True),
        "TNS_End_Percent": _number(candidate, "TNS_End_Percent", integer=True),
        "GP_PAD": _number(candidate, "GP_PAD", integer=True),
        "DP_PAD": _number(candidate, "DP_PAD", integer=True),
        "DPO": _number(candidate, "DPO", integer=True),
        "PIN_ADJ": _number(candidate, "PIN_ADJ"),
        "UP_ADJ": _number(candidate, "UP_ADJ"),
        "LB_ADDON": _number(candidate, "LB_ADDON"),
        "HIER_SYNTH": _number(candidate, "HIER_SYNTH", integer=True),
        "CTS_CSIZE": _number(candidate, "CTS_CSIZE", integer=True),
        "CTS_CDIA": _number(candidate, "CTS_CDIA", integer=True),
    }
    bounds = {
        "CLK": (clk_low, clk_high), "UTIL": (20, 69), "TNS_End_Percent": (0, 100),
        "GP_PAD": (0, 3), "DP_PAD": (0, 3), "DPO": (0, 1),
        "PIN_ADJ": (0.1, 0.7), "UP_ADJ": (0.1, 0.7), "LB_ADDON": (0.0, 0.99),
        "HIER_SYNTH": (0, 1), "CTS_CSIZE": (10, 40), "CTS_CDIA": (80, 120),
    }
    for name, (lower, upper) in bounds.items():
        if not lower <= value[name] <= upper:
            raise ValueError(f"candidate {name}={value[name]!r} is outside upstream range [{lower}, {upper}]")
    return value


def _upstream_job_name(*, design: str, platform: str,
                       candidate: Mapping[str, int | float]) -> str:
    """Return the native ``run_or_job.sh`` FLOW_VARIANT byte-for-byte shape."""
    values = {
        "design": design, "CLK_PERIOD": candidate["CLK"],
        "CORE_UTILIZATION": candidate["UTIL"], "CORE_ASPECT_RATIO": 1,
        "tech": platform, "PLACE_DENSITY_LB_ADDON": candidate["LB_ADDON"],
        "TNS_END_PERCENT": candidate["TNS_End_Percent"], "RECOVER_POWER": 0,
        "SYNTH_HIERARCHICAL": candidate["HIER_SYNTH"],
        "CELL_PAD_IN_SITES_GLOBAL_PLACEMENT": candidate["GP_PAD"],
        "CELL_PAD_IN_SITES_DETAIL_PLACEMENT": candidate["DP_PAD"],
        "GPL_ROUTABILITY_DRIVEN": 1, "GPL_TIMING_DRIVEN": 1,
        "ENABLE_DPO": candidate["DPO"], "CTS_CLUSTER_SIZE": candidate["CTS_CSIZE"],
        "CTS_CLUSTER_DIAMETER": candidate["CTS_CDIA"], "PIN_LAYER_ADJUST": candidate["PIN_ADJ"],
        "UP_LAYER_ADJUST": candidate["UP_ADJ"],
    }
    return (
        "DESIGN_{design}__CLK_{CLK_PERIOD}__UTIL_{CORE_UTILIZATION}"
        "__AR_{CORE_ASPECT_RATIO}__TECH_{tech}__LB_ADDON_{PLACE_DENSITY_LB_ADDON}"
        "__TIMING_EFFORT_{TNS_END_PERCENT}__POWER_EFFORT_{RECOVER_POWER}"
        "__HIER_SYNTH_{SYNTH_HIERARCHICAL}"
        "__GP_PAD_{CELL_PAD_IN_SITES_GLOBAL_PLACEMENT}"
        "__DP_PAD_{CELL_PAD_IN_SITES_DETAIL_PLACEMENT}"
        "__RD_{GPL_ROUTABILITY_DRIVEN}__TD_{GPL_TIMING_DRIVEN}__DPO_{ENABLE_DPO}"
        "__CTS_CSIZE_{CTS_CLUSTER_SIZE}__CTS_CDIA_{CTS_CLUSTER_DIAMETER}"
        "__PIN_ADJ_{PIN_LAYER_ADJUST}__UP_ADJ_{UP_LAYER_ADJUST}"
    ).format(**values)


def _preserve_recursive_makeflags(flow: Path) -> list[dict[str, str]]:
    """Patch only the private paper-flow copy for modern GNU Make transport.

    The pinned paper ``utils.mk`` clears ``MAKEFLAGS`` before every recursive
    ``make``.  That discards command-line directory bindings at the third
    make level, so OpenROAD receives no ``RESULTS_DIR``.  The upstream launcher
    has no alternative non-SSH entrypoint.  Preserve this one GNU Make control
    variable in the copy; no EDA knob, script, source input, or candidate is
    changed.  Exact anchor checking prevents a silent broad patch.
    """
    utils = flow / "util" / "utils.mk"
    original = utils.read_text(encoding="utf-8")
    anchor = "SUB_MAKE% UNSET_VARS%,"
    replacement = "SUB_MAKE% UNSET_VARS% MAKEFLAGS% LOG_DIR% OBJECTS_DIR% REPORTS_DIR% RESULTS_DIR%,"
    if original.count(anchor) != 1:
        raise ValueError("paper flow recursive-Make compatibility anchor is absent or ambiguous")
    patched = original.replace(anchor, replacement)
    utils.write_text(patched, encoding="utf-8")
    write_ref_sdc = flow / "scripts" / "write_ref_sdc.tcl"
    sdc_original = write_ref_sdc.read_text(encoding="utf-8")
    sdc_anchor = '[file join $env(RESULTS_DIR) "updated_clks.sdc"]'
    sdc_replacement = '[file join $::env(RESULTS_DIR) "updated_clks.sdc"]'
    if sdc_original.count(sdc_anchor) != 1:
        raise ValueError("paper flow write_ref_sdc compatibility anchor is absent or ambiguous")
    sdc_patched = sdc_original.replace(sdc_anchor, sdc_replacement)
    write_ref_sdc.write_text(sdc_patched, encoding="utf-8")
    makefile = flow / "Makefile"
    make_original = makefile.read_text(encoding="utf-8")
    make_marker = "# Runtime candidate exports; command-line values must reach Tcl recipes."
    if make_marker in make_original:
        raise ValueError("paper flow candidate-export compatibility marker is already present")
    make_patched = make_original + (
        "\n" + make_marker + "\n"
        "export CLK_PERIOD ABC_CLOCK_PERIOD_IN_PS CORE_UTILIZATION CORE_ASPECT_RATIO "
        "PLACE_DENSITY_LB_ADDON TNS_END_PERCENT RECOVER_POWER SYNTH_HIERARCHICAL "
        "CELL_PAD_IN_SITES_GLOBAL_PLACEMENT CELL_PAD_IN_SITES_DETAIL_PLACEMENT "
        "ENABLE_DPO GPL_TIMING_DRIVEN GPL_ROUTABILITY_DRIVEN CTS_CLUSTER_SIZE "
        "CTS_CLUSTER_DIAMETER PIN_LAYER_ADJUST UP_LAYER_ADJUST FASTROUTE_TCL "
        "IO_PLACER_H IO_PLACER_V\n"
    )
    makefile.write_text(make_patched, encoding="utf-8")
    hier_report = flow / "scripts" / "synth_hier_report.tcl"
    hier_original = hier_report.read_text(encoding="utf-8")
    hier_anchor = '    if { $hierarchy_section == 1 } {\n      if {[regexp { +(\\S+) +.*} $line -> module_name]} {'
    hier_replacement = (
        '    if { $hierarchy_section == 1 && [llength $module_list] > 0 '
        '&& [string trim $line] eq "" } { break }\n'
        '    if { $hierarchy_section == 1 } {\n'
        '      if {[regexp {^\\s+[0-9]+\\s+\\S+\\s+([A-Za-z_][A-Za-z0-9_$]*)\\s*$} $line -> module_name] '
        '&& $module_name ne $::env(DESIGN_NAME) '
        '&& [lsearch -exact $module_list $module_name] < 0} {'
    )
    if hier_original.count(hier_anchor) != 1:
        raise ValueError("paper flow hierarchical-synthesis compatibility anchor is absent or ambiguous")
    hier_patched = hier_original.replace(hier_anchor, hier_replacement)
    hier_stat_anchor = "  foreach module $module_list {\n"
    hier_stat_replacement = (
        "  # Modern Yosys rejects repeated stat -top calls for child modules after\n"
        "  # hierarchy checking.  The parsed hierarchy table already identifies the\n"
        "  # exact non-top modules; with the upstream default threshold of zero all\n"
        "  # of them must be preserved.\n"
        "  foreach module $module_list {\n"
        "    puts \"Preserving module: $module\"\n"
        "    puts $out_script_ptr \"select -module {$module}\"\n"
        "    puts $out_script_ptr \"setattr -mod -set keep_hierarchy 1\"\n"
        "    puts $out_script_ptr \"select -clear\"\n"
        "  }\n"
        "  close $out_script_ptr\n"
        "  return\n\n"
        "  foreach module $module_list {\n"
    )
    if hier_patched.count(hier_stat_anchor) != 1:
        raise ValueError("paper flow hierarchical-stat compatibility anchor is absent or ambiguous")
    hier_patched = hier_patched.replace(hier_stat_anchor, hier_stat_replacement)
    hier_patched = hier_patched.replace(
        "write_keep_hierarchy\n",
        'if {[catch {write_keep_hierarchy} hierarchy_error]} {\n'
        '  puts stderr "hierarchical synthesis failed: $hierarchy_error"\n'
        '  puts stderr $::errorInfo\n'
        '  exit 1\n'
        '}\n',
    )
    hier_report.write_text(hier_patched, encoding="utf-8")
    detail_route = flow / "scripts" / "detail_route.tcl"
    route_original = detail_route.read_text(encoding="utf-8")
    route_anchor = (
        'if {[expr [file exists $::env(REPORTS_DIR)/congestion.rpt] && \\\n'
        '    [file size $::env(REPORTS_DIR)/congestion.rpt] != 0]} {\n'
        '  error "Global routing failed, run `make gui_grt` and load $::env(REPORTS_DIR)/congestion.rpt \\\n'
        '    in DRC viewer to view congestion"\n'
        '}\n'
    )
    route_replacement = (
        'if {[file exists $::env(REPORTS_DIR)/congestion.rpt]} {\n'
        '  if {[file size $::env(REPORTS_DIR)/congestion.rpt] != 0} {\n'
        '    error "Global routing failed, run `make gui_grt` and load $::env(REPORTS_DIR)/congestion.rpt \\\n'
        '      in DRC viewer to view congestion"\n'
        '  }\n'
        '}\n'
    )
    if route_original.count(route_anchor) != 1:
        raise ValueError("paper flow detailed-route congestion compatibility anchor is absent or ambiguous")
    route_patched = route_original.replace(route_anchor, route_replacement)
    deprecated_route_args = (
        'append_env_var additional_args MIN_ROUTING_LAYER -bottom_routing_layer 1\n'
        'append_env_var additional_args MAX_ROUTING_LAYER -top_routing_layer 1\n'
    )
    if route_patched.count(deprecated_route_args) != 1:
        raise ValueError("paper flow detailed-route layer compatibility anchor is absent or ambiguous")
    route_patched = route_patched.replace(
        deprecated_route_args,
        '# Current OpenROAD rejects these deprecated flags; set_routing_layers below remains authoritative.\n',
    )
    detail_route.write_text(route_patched, encoding="utf-8")
    final_report = flow / "scripts" / "final_report.tcl"
    final_original = final_report.read_text(encoding="utf-8")
    final_anchor = 'if {[expr [llength [info procs save_image]] > 0]} {\n    gui::show "source $::env(SCRIPTS_DIR)/save_images.tcl" false\n}\n'
    final_replacement = 'if {[llength [info commands gui::show]] > 0 && [llength [info commands gui::load_drc]] > 0 && [llength [info procs save_image]] > 0} {\n    gui::show "source $::env(SCRIPTS_DIR)/save_images.tcl" false\n}\n'
    if final_original.count(final_anchor) != 1:
        raise ValueError("paper flow final-report GUI compatibility anchor is absent or ambiguous")
    final_patched = final_original.replace(final_anchor, final_replacement)
    final_report.write_text(final_patched, encoding="utf-8")
    return [
        {"path": str(utils.relative_to(flow)), "before_sha256": hashlib.sha256(original.encode()).hexdigest(),
         "after_sha256": hashlib.sha256(patched.encode()).hexdigest(),
         "purpose": "preserve GNU Make command-line bindings and derived attempt directories across private recursive make"},
        {"path": str(write_ref_sdc.relative_to(flow)), "before_sha256": hashlib.sha256(sdc_original.encode()).hexdigest(),
         "after_sha256": hashlib.sha256(sdc_patched.encode()).hexdigest(),
         "purpose": "repair the upstream Tcl procedure's namespace lookup for the Runtime-provided results directory"},
        {"path": str(makefile.relative_to(flow)), "before_sha256": hashlib.sha256(make_original.encode()).hexdigest(),
         "after_sha256": hashlib.sha256(make_patched.encode()).hexdigest(),
         "purpose": "export the upstream candidate variables supplied as make command-line bindings to ORFS Tcl recipes"},
        {"path": str(hier_report.relative_to(flow)), "before_sha256": hashlib.sha256(hier_original.encode()).hexdigest(),
         "after_sha256": hashlib.sha256(hier_patched.encode()).hexdigest(),
         "purpose": "ignore Yosys hierarchy-stat table headings so the paper hierarchical-synthesis path selects only real module names"},
        {"path": str(detail_route.relative_to(flow)), "before_sha256": hashlib.sha256(route_original.encode()).hexdigest(),
         "after_sha256": hashlib.sha256(route_patched.encode()).hexdigest(),
         "purpose": "avoid evaluating file size for a missing empty congestion report after a congestion-free global route"},
        {"path": str(final_report.relative_to(flow)), "before_sha256": hashlib.sha256(final_original.encode()).hexdigest(),
         "after_sha256": hashlib.sha256(final_patched.encode()).hexdigest(),
         "purpose": "skip the GUI-only final image hook unless the current OpenROAD Tcl exposes every GUI command used by save_images.tcl"},
    ]


def _materialize(root: Path, *, source: Path, paper_orfs: Path,
                 platform: str, design: str, candidate: Mapping[str, int | float]) -> dict[str, Any]:
    """Create the exact upstream run_or_job input shape within one attempt."""
    flow_source = paper_orfs / "flow"
    private_source = source / "AutoTuner-integration" / "AutoTuner" / "autotune_configs"
    if not flow_source.is_dir() or not private_source.is_dir():
        raise FileNotFoundError("pinned paper flow or ORFS-Agent AutoTuner configs are absent")
    flow = root / "orfs-flow"
    private = root / "autotune-configs"
    # root is Runtime-created and guaranteed empty for a fresh attempt.
    shutil.copytree(flow_source, flow, symlinks=True)
    shutil.copytree(private_source, private, symlinks=True)
    compatibility_patch = _preserve_recursive_makeflags(flow)
    config = private / f"{design}_{platform}.mk"
    sdc = private / ({"aes": "aes_cipher_top.sdc", "ibex": "ibex_core.sdc", "jpeg": "jpeg_encoder.sdc"}[design])
    route = private / f"fastroute_{platform}.tcl"
    for path in (config, sdc, route):
        if not path.is_file():
            raise FileNotFoundError(f"upstream material required for candidate is absent: {path}")
    work_home = root / "work"
    variant = _upstream_job_name(design=design, platform=platform, candidate=candidate)
    # This mapping is a direct transcription of upstream run_or_job.sh.  The
    # values deliberately remain environment variables (rather than a new
    # generated optimizer config) so ORFS evaluates exactly its native knobs.
    environment = {
        "CLK_PERIOD": str(candidate["CLK"]),
        "ABC_CLOCK_PERIOD_IN_PS": str(candidate["CLK"]),
        "CORE_UTILIZATION": str(candidate["UTIL"]),
        "CORE_ASPECT_RATIO": "1",
        "PLACE_DENSITY_LB_ADDON": str(candidate["LB_ADDON"]),
        "TNS_END_PERCENT": str(candidate["TNS_End_Percent"]),
        "RECOVER_POWER": "0",
        "SYNTH_HIERARCHICAL": str(candidate["HIER_SYNTH"]),
        "CELL_PAD_IN_SITES_GLOBAL_PLACEMENT": str(candidate["GP_PAD"]),
        "CELL_PAD_IN_SITES_DETAIL_PLACEMENT": str(candidate["DP_PAD"]),
        "ENABLE_DPO": str(candidate["DPO"]),
        "GPL_TIMING_DRIVEN": "1",
        "GPL_ROUTABILITY_DRIVEN": "1",
        "CTS_CLUSTER_SIZE": str(candidate["CTS_CSIZE"]),
        "CTS_CLUSTER_DIAMETER": str(candidate["CTS_CDIA"]),
        "PIN_LAYER_ADJUST": str(candidate["PIN_ADJ"]),
        "UP_LAYER_ADJUST": str(candidate["UP_ADJ"]),
        "FASTROUTE_TCL": str(route),
        # Exact platform selection from upstream run_or_job.sh.
        **({"IO_PLACER_H": "M4 M6", "IO_PLACER_V": "M5 M7"}
           if platform == "asap7" else {"IO_PLACER_H": "met3", "IO_PLACER_V": "met2"}),
        "RUN_DIR": str(private),
        # Never inherit an operator's unrelated ORFS checkout.  The copied
        # flow is the only flow authority for this Runtime attempt.
        "FLOW_HOME": str(flow),
        "WORK_HOME": str(work_home),
        "FLOW_VARIANT": variant,
        # Directly inherited from the upstream launcher.  Keeping this bounded
        # profile also prevents one Runtime attempt from consuming the host.
        "NUM_CORES": "4",
        "OMP_NUM_THREADS": "4",
        "MKL_NUM_THREADS": "4",
    }
    environment["CTS_ARGS"] = (
        "-sink_clustering_enable -balance_levels "
        f"-sink_clustering_size {candidate['CTS_CSIZE']} "
        f"-sink_clustering_max_diameter {candidate['CTS_CDIA']}"
    )
    # The copied upstream config contains only a subset of the 12 knobs.
    # Materialize a candidate-specific config with exported assignments so
    # every recursive Make and the final Tcl process receive the same values.
    # The upstream source itself remains untouched.
    mapped_config = root / "mapped_config.mk"
    mapped_config.write_text(
        config.read_text(encoding="utf-8") + "\n# Runtime materialized upstream candidate\n"
        + "".join(f"export {name} = {environment[name]}\n" for name in CANDIDATE_ENVIRONMENT_VARIABLES),
        encoding="utf-8",
    )
    receipt = {
        "schema_version": 1,
        "kind": "orfs-agent-paper-candidate-materialization",
        "platform": platform,
        "design": design,
        "candidate": dict(candidate),
        "upstream_wrapper": "AutoTuner-integration/ORFS-with-AutoTuner/run_or_job.sh",
        "native_environment_mapping": environment,
        "flow": str(flow),
        "private_flow_compatibility_patch": compatibility_patch,
        "private_config": str(mapped_config),
        "private_sdc": str(sdc),
        "private_fastroute": str(route),
        "expected_report_directory": str(work_home / "logs" / platform / design / variant),
        "expected_result_directory": str(work_home / "results" / platform / design / variant),
        "expected_object_directory": str(work_home / "objects" / platform / design / variant),
        "expected_metrics_directory": str(work_home / "reports" / platform / design / variant),
    }
    _write(root / "candidate_materialization.json", receipt)
    return receipt


def _copy_report(root: Path, materialization: Mapping[str, Any]) -> dict[str, Any]:
    reports = Path(str(materialization["expected_report_directory"]))
    final = reports / "6_report.json"
    cts = reports / "4_1_cts.json"
    if not final.is_file() or final.stat().st_size == 0:
        raise FileNotFoundError(f"ORFS did not emit final report: {final}")
    final_metrics = json.loads(final.read_text(encoding="utf-8"))
    cts_metrics = (json.loads(cts.read_text(encoding="utf-8")) if cts.is_file() else {})
    candidate = materialization["candidate"]
    metrics = {
        "schema_version": 1,
        "raw_final_report": final_metrics,
        "raw_cts_report": cts_metrics,
        "ECP_final": float(candidate["CLK"]) - float(final_metrics["finish__timing__setup__ws"]),
        "ECP_cts": (float(candidate["CLK"]) - float(cts_metrics["cts__timing__setup__ws"])
                    if "cts__timing__setup__ws" in cts_metrics else None),
        "candidate_clock_units": "ps" if materialization["platform"] == "asap7" else "ns",
    }
    _write(root / "candidate_metrics.json", metrics)
    return metrics


def _result(*, status: str, code: int, started: str, artifacts: list[dict[str, str]],
            provenance: Mapping[str, Any], failure: Mapping[str, str] | None = None) -> dict[str, Any]:
    return {"schema_version": 1, "status": status, "exit_code": code,
            "started_at": started, "ended_at": _now(), "metrics": [],
            "artifacts": artifacts, "failure": failure, "provenance": dict(provenance)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    started = _now()
    try:
        request = json.loads(args.request.read_text(encoding="utf-8"))
        task = request["task"]
        if request.get("plugin", {}).get("plugin_id") != "orfs-agent-paper-reproduction":
            raise ValueError("request is not for orfs-agent-paper-reproduction")
        inputs = task.get("inputs")
        if not isinstance(inputs, Mapping):
            raise ValueError("task inputs must be an object")
        platform, design = str(inputs.get("platform", "")), str(inputs.get("design", ""))
        if platform not in SUPPORTED_PLATFORMS or design not in SUPPORTED_DESIGNS:
            raise ValueError("paper reproduction supports {aes,ibex,jpeg} on {asap7,sky130hd}")
        raw_candidate = inputs.get("candidate")
        if not isinstance(raw_candidate, Mapping):
            raise ValueError("task inputs require a 12-field candidate object")
        candidate = validate_candidate(raw_candidate, platform=platform)
        source = _required_path("ORFS_AGENT_SOURCE")
        paper_orfs = _required_path("ORFS_AGENT_PAPER_ORFS_ROOT")
        openroad = _required_path("OPENROAD_BIN")
        yosys = _required_path("YOSYS_BIN")
        source_receipt = _check_clean_git(source, os.environ["ORFS_AGENT_EXPECTED_COMMIT"], "ORFS-Agent")
        flow_receipt = _check_clean_git(paper_orfs, os.environ["ORFS_AGENT_PAPER_ORFS_COMMIT"], "paper ORFS")
        root = args.result.parent.resolve()
        materialization = _materialize(root, source=source, paper_orfs=paper_orfs,
                                       platform=platform, design=design, candidate=candidate)
        environment = dict(os.environ)
        environment.update(materialization["native_environment_mapping"])
        environment.update({
            "LOG_DIR": str(materialization["expected_report_directory"]),
            "RESULTS_DIR": str(materialization["expected_result_directory"]),
            "OBJECTS_DIR": str(materialization["expected_object_directory"]),
            "REPORTS_DIR": str(materialization["expected_metrics_directory"]),
        })
        environment["OPENROAD_EXE"] = str(openroad)
        environment["YOSYS_EXE"] = str(yosys)
        environment["PATH"] = os.pathsep.join((str(openroad.parent), str(yosys.parent), environment.get("PATH", os.defpath)))
        native = materialization["native_environment_mapping"]
        # The pinned flow deliberately clears environment-origin variables
        # before recursive make invocations.  Candidate knobs therefore must
        # be command-line assignments, exactly like the directory bindings;
        # exporting them alone would merely record transmission while ORFS
        # silently reverts to its config defaults.
        # ORFS' recursive make wrapper deliberately clears environment-origin
        # variables.  Pass the derived directories as GNU Make command-line
        # variables so every child make reconstitutes the same native paths.
        command = (
            "make", "tunereport", f"PRIVATE_DIR={native['RUN_DIR']}",
            f"DESIGN_CONFIG={materialization['private_config']}",
            f"FLOW_HOME={native['FLOW_HOME']}", f"WORK_HOME={native['WORK_HOME']}",
            f"FLOW_VARIANT={native['FLOW_VARIANT']}",
            f"LOG_DIR={materialization['expected_report_directory']}",
            f"RESULTS_DIR={materialization['expected_result_directory']}",
            f"OBJECTS_DIR={materialization['expected_object_directory']}",
            f"REPORTS_DIR={materialization['expected_metrics_directory']}",
            "NUM_CORES=4", "OMP_NUM_THREADS=4", "MKL_NUM_THREADS=4",
            *(f"{name}={native[name]}" for name in CANDIDATE_ENVIRONMENT_VARIABLES),
        )
        completed = subprocess.run(command, cwd=materialization["flow"], env=environment,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
        (root / "orfs_agent_native_make.log").write_text(completed.stdout, encoding="utf-8", errors="replace")
        if completed.returncode != 0:
            raise RuntimeError(f"upstream-style make tunereport exited {completed.returncode}")
        metrics = _copy_report(root, materialization)
        provenance = {"adapter": "orfs-agent-paper-reproduction-executor",
                      "source": source_receipt, "paper_orfs": flow_receipt,
                      "openroad": str(openroad), "yosys": str(yosys),
                      "full_upstream_domain": list(PARAMETERS),
                      "note": "candidate-specific CLK is original ORFS-Agent reproduction semantics, not fair fixed-SDC PPA"}
        _write(root / "reproduction_provenance.json", provenance)
        artifacts = [
            {"kind": "optimizer_input_manifest", "path": "candidate_materialization.json"},
            {"kind": "optimizer_dataset", "path": "candidate_metrics.json"},
            {"kind": "upstream_source_lock", "path": "reproduction_provenance.json"},
            {"kind": "log", "path": "orfs_agent_native_make.log"},
            {"kind": "report", "path": "candidate_metrics.json"},
        ]
        args.result.write_text(json.dumps(_result(status="succeeded", code=0, started=started,
            artifacts=artifacts, provenance=provenance), indent=2), encoding="utf-8")
        return 0
    except Exception as exc:
        # A terminal flow failure is experiment evidence, not an excuse to
        # discard its candidate, materialized config, or raw make log.  These
        # paths are intentionally relative to this isolated attempt root.
        failed_root = locals().get("root")
        failed_artifacts: list[dict[str, str]] = []
        if isinstance(failed_root, Path):
            for kind, filename in (
                ("optimizer_input_manifest", "candidate_materialization.json"),
                ("log", "orfs_agent_native_make.log"),
            ):
                if (failed_root / filename).is_file():
                    failed_artifacts.append({"kind": kind, "path": filename})
            if (failed_root / "mapped_config.mk").is_file():
                failed_artifacts.append({"kind": "mapped_orfs_config", "path": "mapped_config.mk"})
        args.result.write_text(json.dumps(_result(status="failed", code=2, started=started,
            artifacts=failed_artifacts,
            provenance={"adapter": "orfs-agent-paper-reproduction-executor"},
            failure={"category": "flow_or_adapter_failure", "message": str(exc)}), indent=2), encoding="utf-8")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
