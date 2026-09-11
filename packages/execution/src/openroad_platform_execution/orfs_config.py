from __future__ import annotations

import re
import shutil
from pathlib import Path


CLOCK_CANDIDATES = ("clk", "clock", "i_clk", "clk_i", "sys_clk", "clk_in")

# Public API and RunRequest periods are always ns.  SDC numeric literals are
# expressed in the active platform Liberty unit, which is ps for ASAP7 and ns
# for the other currently supported open PDK platforms.  Keeping this at the
# execution boundary prevents UI/API data from acquiring PDK-dependent units.
PLATFORM_TIME_UNIT_NS = {"asap7": 1e-3}


def clock_period_in_platform_units(clock_period_ns: float, platform: str) -> float:
    unit_ns = PLATFORM_TIME_UNIT_NS.get(platform, 1.0)
    return float(clock_period_ns) / unit_ns

PDN_SIMPLE = """\
add_global_connection -net {VDD} -inst_pattern {.*} -pin_pattern {^VDD$} -power
add_global_connection -net {VSS} -inst_pattern {.*} -pin_pattern {^VSS$} -ground
global_connect
set_voltage_domain -name {CORE} -power {VDD} -ground {VSS}
define_pdn_grid -name {grid} -voltage_domains {CORE} -pins {metal7}
add_pdn_stripe -grid {grid} -layer {metal1} -width {0.17} -pitch {2.4} -offset {0} -followpins
add_pdn_stripe -grid {grid} -layer {metal4} -width {0.48} -pitch {6.0} -offset {0.3}
add_pdn_stripe -grid {grid} -layer {metal7} -width {0.40} -pitch {3.0} -offset {0.1}
add_pdn_connect -grid {grid} -layers {metal1 metal4}
add_pdn_connect -grid {grid} -layers {metal4 metal7}
"""


def strip_comments(rtl: str) -> str:
    rtl = re.sub(r"/\*.*?\*/", " ", rtl, flags=re.S)
    return re.sub(r"//[^\n]*", " ", rtl)


def infer_top(rtl: str, fallback: str) -> str:
    code = strip_comments(rtl)
    defined = re.findall(r"\bmodule\s+(\w+)", code)
    if not defined:
        raise ValueError("RTL does not contain a module declaration")
    keywords = {"module", "endmodule", "input", "output", "inout", "wire",
                "reg", "assign", "always", "if", "else", "case", "begin", "end"}
    instantiated = {
        item for item in re.findall(
            r"^\s*(\w+)\s*(?:#\s*\([^)]*\)\s*)?\w+\s*\(", code, flags=re.M
        ) if item not in keywords
    }
    candidates = [item for item in defined if item not in instantiated]
    if len(candidates) == 1:
        return candidates[0]
    if fallback in defined:
        return fallback
    return candidates[0] if candidates else defined[-1]


def infer_clock(rtl: str, top: str) -> str | None:
    code = strip_comments(rtl)
    match = re.search(rf"\bmodule\s+{re.escape(top)}\b(.*?)\bendmodule\b", code, re.S)
    body = match.group(1) if match else code
    ports = set(re.findall(
        r"\binput\s+(?:wire\s+|reg\s+)?(?:\[[^\]]*\]\s*)?(\w+)", body
    ))
    ports |= set(re.findall(r"\w+", body.split(";", 1)[0]))
    for candidate in CLOCK_CANDIDATES:
        if candidate in ports:
            return candidate
    return next((port for port in ports if re.search(r"cl(?:k|ock)", port, re.I)), None)


def write_design_files(
    *,
    workdir: Path,
    rtl_path: Path,
    design: str,
    platform: str,
    clock: str | None,
    clock_period_ns: float,
    core_utilization_pct: float,
    place_density: float,
    or_seed: int = 1,
    minimum_die_size_um: float | None = None,
    flow_parameters: dict | None = None,
    rtl_files: tuple[Path, ...] = (),
    rtl_root: Path | None = None,
    rtl_include_dirs: tuple[Path, ...] = (),
    synth_hdl_frontend: str | None = None,
    design_options: dict | None = None,
    sdc_path: Path | None = None,
    fast_route_tcl_path: Path | None = None,
) -> Path:
    from .orfs_parameters import orfs_parameter_config_lines, validate_orfs_parameters
    from .orfs_design_options import orfs_design_option_config_lines

    tuning = validate_orfs_parameters(flow_parameters or {}, platform=platform)
    clock_period_native = clock_period_in_platform_units(clock_period_ns, platform)
    core_utilization_pct = tuning.get("core_utilization_pct", core_utilization_pct)
    place_density = tuning.get("place_density", place_density)
    config_dir = workdir / "designs" / platform / design
    source_dir = workdir / "designs" / "src" / design
    config_dir.mkdir(parents=True, exist_ok=True)
    source_dir.mkdir(parents=True, exist_ok=True)
    staged_sources: list[Path] = []
    staged_include_dirs: list[Path] = []
    if rtl_files:
        if rtl_root is None:
            raise ValueError("rtl_root is required for a multi-file bundle")
        root = rtl_root.expanduser().resolve()
        for source in rtl_files:
            source = source.expanduser().resolve()
            relative = source.relative_to(root)
            target = source_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            staged_sources.append(target)
        for directory in rtl_include_dirs:
            directory = directory.expanduser().resolve()
            relative = directory.relative_to(root)
            target_dir = source_dir / relative
            target_dir.mkdir(parents=True, exist_ok=True)
            for header in sorted(directory.rglob("*")):
                if header.is_file() and header.suffix.lower() in {".v", ".sv", ".vh", ".svh"}:
                    target = target_dir / header.relative_to(directory)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(header, target)
            staged_include_dirs.append(target_dir)
    else:
        target = source_dir / f"{design}{rtl_path.suffix.lower() or '.v'}"
        shutil.copyfile(rtl_path, target)
        staged_sources.append(target)

    lines = [
        f"export DESIGN_NAME = {design}",
        f"export PLATFORM = {platform}",
        "export VERILOG_FILES = " + " ".join(str(item) for item in staged_sources),
        f"export SDC_FILE = $(DESIGN_HOME)/{platform}/$(DESIGN_NAME)/constraint.sdc",
        f"export CLOCK_PERIOD = {clock_period_native:g}",
        f"export OR_SEED = {or_seed}",
    ]
    # ORFS treats PLACE_DENSITY and PLACE_DENSITY_LB_ADDON as alternative
    # policies.  Emitting both is physically deterministic (the addon wins in
    # util.tcl) but leaves an inactive contradictory value in evidence.  Keep
    # the generated configuration single-policy and auditable.
    if "place_density_lb_addon" not in tuning:
        lines.append(f"export PLACE_DENSITY = {place_density:g}")
    if staged_include_dirs:
        lines.append("export VERILOG_INCLUDE_DIRS = " + " ".join(
            str(item) for item in staged_include_dirs))
    if synth_hdl_frontend:
        lines.append(f"export SYNTH_HDL_FRONTEND = {synth_hdl_frontend}")
    lines.extend(orfs_design_option_config_lines(design_options))
    if platform == "nangate45":
        (config_dir / "pdn.tcl").write_text(PDN_SIMPLE, encoding="utf-8")
        lines.append(f"export PDN_TCL = $(DESIGN_HOME)/{platform}/$(DESIGN_NAME)/pdn.tcl")
        if minimum_die_size_um is not None:
            size = float(minimum_die_size_um)
            margin = max(1.0, min(10.0, size * 0.1))
            lines.extend((
                f"export DIE_AREA = 0 0 {size:g} {size:g}",
                f"export CORE_AREA = {margin:g} {margin:g} {size-margin:g} {size-margin:g}",
            ))
        else:
            lines.append(f"export CORE_UTILIZATION = {core_utilization_pct:g}")
    else:
        # ORFS needs one complete floorplan-initialisation policy.  A DIE_AREA
        # on its own deliberately disables its automatic utilisation-based
        # sizing, but still leaves no CORE_AREA for ``initialize_floorplan``.
        # That used to make every generated sky130/asap7/gf180 task stop at
        # floorplan with "No floorplan initialization method specified".
        #
        # Use the requested utilization for the normal, scalable case.  When
        # a caller explicitly asks for a minimum die size, provide both die and
        # core rectangles so that this remains a complete, valid alternative.
        if minimum_die_size_um is None:
            lines.append(f"export CORE_UTILIZATION = {core_utilization_pct:g}")
        else:
            size = float(minimum_die_size_um)
            margin = max(1.0, min(10.0, size * 0.1))
            lines.extend((
                f"export DIE_AREA = 0 0 {size:g} {size:g}",
                f"export CORE_AREA = {margin:g} {margin:g} {size-margin:g} {size-margin:g}",
            ))

    if fast_route_tcl_path is not None:
        source_fast_route = fast_route_tcl_path.expanduser().resolve()
        if not source_fast_route.is_file() or source_fast_route.stat().st_size == 0:
            raise FileNotFoundError(source_fast_route)
        staged_fast_route = config_dir / "fastroute.tcl"
        shutil.copyfile(source_fast_route, staged_fast_route)
        lines.append(
            "export FASTROUTE_TCL = "
            f"$(DESIGN_HOME)/{platform}/$(DESIGN_NAME)/fastroute.tcl"
        )

    extra_tuning = {name: value for name, value in tuning.items()
                    if name not in {"core_utilization_pct", "place_density"}}
    lines.extend(orfs_parameter_config_lines(extra_tuning, platform=platform))
    config_path = config_dir / "config.mk"
    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    constraint_path = config_dir / "constraint.sdc"
    if sdc_path is not None:
        shutil.copyfile(sdc_path.expanduser().resolve(), constraint_path)
    elif clock:
        sdc = (
            f"create_clock -name {clock} -period {clock_period_native:g} [get_ports {{{clock}}}]\n"
            f"set_input_delay -clock {clock} [expr {clock_period_native:g} * 0.2] [all_inputs]\n"
            f"set_output_delay -clock {clock} [expr {clock_period_native:g} * 0.2] [all_outputs]\n"
        )
    else:
        sdc = (
            f"create_clock -name vclk -period {clock_period_native:g}\n"
            f"set_input_delay -clock vclk [expr {clock_period_native:g} * 0.2] [all_inputs]\n"
            f"set_output_delay -clock vclk [expr {clock_period_native:g} * 0.2] [all_outputs]\n"
        )
    if sdc_path is None:
        constraint_path.write_text(sdc, encoding="utf-8")
    return config_path
