"""Typed, allowlisted ORFS tuning parameters and effective-value evidence."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class ORFSParameter:
    name: str
    env_name: str
    kind: str
    stage: str
    lower: float | None = None
    upper: float | None = None
    step: float | None = None
    choices: tuple[Any, ...] = ()
    platforms: tuple[str, ...] = ()
    consumer_path: str = "scripts/variables.yaml"
    runtime_patterns: tuple[str, ...] = ()

    def canonicalize(self, raw: Any) -> Any:
        if self.kind == "bool":
            if raw is True or raw == 1:
                value = 1
            elif raw is False or raw == 0:
                value = 0
            else:
                raise ValueError(f"{self.name} must be boolean")
        elif self.kind == "int":
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                raise ValueError(f"{self.name} must be an integer")
            value = int(raw)
            if float(raw) != value:
                raise ValueError(f"{self.name} must be an integer")
        elif self.kind == "float":
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                raise ValueError(f"{self.name} must be numeric")
            value = float(raw)
            if not math.isfinite(value):
                raise ValueError(f"{self.name} must be finite")
        elif self.kind == "categorical":
            value = raw
        else:
            raise ValueError(f"Unsupported parameter kind: {self.kind}")
        if self.choices and value not in self.choices:
            raise ValueError(f"{self.name} is not in its allowlisted choices")
        if self.lower is not None and value < self.lower:
            raise ValueError(f"{self.name} is below its lower bound")
        if self.upper is not None and value > self.upper:
            raise ValueError(f"{self.name} is above its upper bound")
        if self.step and self.lower is not None:
            units = (float(value) - self.lower) / self.step
            if abs(units - round(units)) > 1e-8:
                raise ValueError(f"{self.name} does not align with its quantization step")
        return value


# Clock and SDC constraints are deliberately absent: QoR optimization must not
# improve its score by weakening the design target.
ORFS_PARAMETERS = (
    ORFSParameter("core_utilization_pct", "CORE_UTILIZATION", "int", "floorplan", 20, 80, 1,
                  runtime_patterns=(r"Defining die area using utilization:\s*{value}(?:\.0+)?%",)),
    ORFSParameter("place_density", "PLACE_DENSITY", "float", "place", .30, .90, .01,
                  runtime_patterns=(r"Placement target density:\s*{value}",)),
    # ORFS-Agent models LB_ADDON as a continuous Real dimension.  OpenROAD
    # consumes the value as a Tcl numeric literal, so imposing a platform
    # grid would silently turn multiple GP/EI proposals into the same run.
    ORFSParameter("place_density_lb_addon", "PLACE_DENSITY_LB_ADDON", "float", "place", 0, .50,
                  runtime_patterns=(r"computed from PLACE_DENSITY_LB_ADDON\s+{value}",)),
    ORFSParameter("tns_end_percent", "TNS_END_PERCENT", "int", "place", 0, 100, 1,
                  consumer_path="scripts/repair_timing_post_place.tcl",
                  runtime_patterns=(r"repair_timing[^\n]*-repair_tns\s+{value}",)),
    ORFSParameter("global_placement_padding", "CELL_PAD_IN_SITES_GLOBAL_PLACEMENT", "int", "place", 0, 4, 1,
                  consumer_path="scripts/global_place.tcl",
                  runtime_patterns=(r"global_placement[^\n]*-pad_left\s+{value}\s+-pad_right\s+{value}",)),
    ORFSParameter("detail_placement_padding", "CELL_PAD_IN_SITES_DETAIL_PLACEMENT", "int", "place", 0, 4, 1,
                  consumer_path="scripts/detail_place.tcl"),
    ORFSParameter("enable_dpo", "ENABLE_DPO", "bool", "place", choices=(0, 1),
                  consumer_path="scripts/detail_place.tcl",
                  runtime_patterns=(r"Detailed placement improvement\.",)),
    ORFSParameter("gpl_timing_driven", "GPL_TIMING_DRIVEN", "bool", "place", choices=(0, 1),
                  consumer_path="scripts/global_place.tcl",
                  runtime_patterns=(r"global_placement[^\n]*-timing_driven",)),
    ORFSParameter("gpl_routability_driven", "GPL_ROUTABILITY_DRIVEN", "bool", "place", choices=(0, 1),
                  consumer_path="scripts/global_place.tcl",
                  runtime_patterns=(r"global_placement[^\n]*-routability_driven",)),
    ORFSParameter("routing_layer_adjustment", "ROUTING_LAYER_ADJUSTMENT", "float", "floorplan", .10, .90, .01,
                  consumer_path="scripts/floorplan.tcl"),
    ORFSParameter("cts_cluster_size", "CTS_CLUSTER_SIZE", "int", "cts", 10, 40, 1,
                  consumer_path="scripts/cts.tcl",
                  runtime_patterns=(r"clock_tree_synthesis[^\n]*-sink_clustering_size\s+{value}",)),
    ORFSParameter("cts_cluster_diameter", "CTS_CLUSTER_DIAMETER", "float", "cts", 40, 120, 1,
                  consumer_path="scripts/cts.tcl",
                  runtime_patterns=(r"clock_tree_synthesis[^\n]*-sink_clustering_max_diameter\s+{value}(?:\.0+)?",)),
)
ORFS_PARAMETER_BY_NAME = {item.name: item for item in ORFS_PARAMETERS}

ORFS_PLATFORM_BOUNDS = {
    "nangate45": {"core_utilization_pct": (20, 80), "place_density": (.30, .80),
                   "global_placement_padding": (0, 3), "detail_placement_padding": (0, 3)},
    "asap7": {"core_utilization_pct": (30, 75), "place_density": (.35, .80),
              "global_placement_padding": (0, 3), "detail_placement_padding": (0, 3)},
    # ORFS-Agent's published SKY130HD/AES anchor uses UTIL=20.  Preserve that
    # reviewed upstream lower bound instead of silently rejecting its official
    # starting configuration at the platform transport gate.
    "sky130hd": {"core_utilization_pct": (20, 70), "place_density": (.30, .75),
                  "global_placement_padding": (0, 3), "detail_placement_padding": (0, 3)},
}


def validate_orfs_parameters(parameters: Mapping[str, Any], *, platform: str) -> dict[str, Any]:
    unknown = sorted(set(parameters) - set(ORFS_PARAMETER_BY_NAME))
    if unknown:
        raise ValueError(f"Unsupported ORFS tuning parameters: {', '.join(unknown)}")
    result = {}
    for name, raw in parameters.items():
        spec = ORFS_PARAMETER_BY_NAME[name]
        if spec.platforms and platform not in spec.platforms:
            raise ValueError(f"{name} is not supported on {platform}")
        result[name] = spec.canonicalize(raw)
        platform_bound = ORFS_PLATFORM_BOUNDS.get(platform, {}).get(name)
        if platform_bound and not platform_bound[0] <= result[name] <= platform_bound[1]:
            raise ValueError(f"{name} is outside the calibrated range for {platform}")
    global_pad = result.get("global_placement_padding")
    detail_pad = result.get("detail_placement_padding")
    if global_pad is not None and detail_pad is not None and detail_pad > global_pad:
        raise ValueError("detail_placement_padding cannot exceed global_placement_padding")
    if "place_density" in result and "place_density_lb_addon" in result:
        raise ValueError("place_density and place_density_lb_addon are alternative policies")
    return dict(sorted(result.items()))


def effective_configuration_id(parameters: Mapping[str, Any], *, platform: str) -> str:
    canonical = validate_orfs_parameters(parameters, platform=platform)
    payload = {"schema_version": 1, "platform": platform, "parameters": canonical}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return f"orfs-effective-{digest}"


def orfs_parameter_config_lines(parameters: Mapping[str, Any], *, platform: str) -> list[str]:
    canonical = validate_orfs_parameters(parameters, platform=platform)
    return [f"export {ORFS_PARAMETER_BY_NAME[name].env_name} = {value}"
            for name, value in canonical.items()]


def orfs_parameter_schema() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "liveness_rule_version": "orfs-runtime-patterns-v2",
        "frozen_constraints": ("clock_period_ns", "clock_uncertainty", "io_delay"),
        "parameters": [item.__dict__ for item in ORFS_PARAMETERS],
        "platform_bounds": ORFS_PLATFORM_BOUNDS,
    }


def parameter_source_evidence(flow_home: str | Path,
                              parameters: Mapping[str, Any]) -> list[dict[str, Any]]:
    root = Path(flow_home).expanduser().resolve()
    rows = []
    for name in sorted(parameters):
        spec = ORFS_PARAMETER_BY_NAME[name]
        path = root / spec.consumer_path
        content = path.read_bytes() if path.is_file() else b""
        rows.append({
            "name": name,
            "env_name": spec.env_name,
            "consumer_path": str(path),
            "consumer_sha256": hashlib.sha256(content).hexdigest() if content else None,
            "consumer_declared": spec.env_name.encode() in content,
            "stage": spec.stage,
            "runtime_patterns": spec.runtime_patterns,
        })
    return rows


def orfs_optimization_profile(platform: str) -> dict[str, Any]:
    """Server-owned v2 search space; no timing constraint is tunable."""
    defaults = {
        "nangate45": {"core_utilization_pct": 55},
        "asap7": {"core_utilization_pct": 65},
        "sky130hd": {"core_utilization_pct": 40},
    }
    if platform not in defaults:
        raise ValueError(f"No calibrated industrial optimization profile for {platform}")
    baseline = {
        **defaults[platform], "place_density_lb_addon": .20,
        "tns_end_percent": 100, "global_placement_padding": 0,
        "detail_placement_padding": 0, "enable_dpo": 1,
        "gpl_timing_driven": 1, "gpl_routability_driven": 1,
        "routing_layer_adjustment": .50, "cts_cluster_size": 20,
        "cts_cluster_diameter": 50.0,
    }
    specs = []
    for name in baseline:
        item = ORFS_PARAMETER_BY_NAME[name]
        lower, upper = ORFS_PLATFORM_BOUNDS.get(platform, {}).get(
            name, (item.lower, item.upper))
        specs.append({
            "name": name, "kind": item.kind, "lower": lower, "upper": upper,
            "choices": item.choices, "step": item.step, "stage": item.stage,
            "active_when": {},
            "less_than_or_equal_to": (
                "global_placement_padding"
                if name == "detail_placement_padding" else None
            ),
        })
    validate_orfs_parameters(baseline, platform=platform)
    return {
        "schema_version": 1, "platform": platform, "baseline": baseline,
        "parameter_space": specs,
        "frozen_constraints": ("clock_period_ns", "clock_uncertainty", "io_delay"),
        "claim_boundary": "ranges are ORFS-policy bounds; parameter liveness must be calibrated per pinned toolchain",
    }


def apply_parameter_calibration(profile: Mapping[str, Any],
                                report: Mapping[str, Any]) -> dict[str, Any]:
    """Filter a server-owned profile through an immutable liveness report.

    Calibration is deliberately subtractive: it can remove unresolved knobs,
    but it cannot add names, widen ranges, or alter frozen constraints.
    """
    platform = str(profile.get("platform") or "")
    if report.get("protocol") != "single-knob-low-mid-high-three-paired-seeds-v1":
        raise ValueError("unsupported ORFS parameter calibration protocol")
    rows = [row for row in report.get("parameters", [])
            if row.get("platform") == platform]
    if not rows:
        raise ValueError(f"parameter calibration has no evidence for {platform}")
    by_name = {str(row.get("parameter")): row for row in rows}
    declared = {str(item["name"]) for item in profile.get("parameter_space", [])}
    unknown = sorted(set(by_name) - declared)
    if unknown:
        raise ValueError(f"calibration contains parameters outside the profile: {', '.join(unknown)}")
    eligible = {name for name, row in by_name.items()
                if row.get("search_eligible") is True}
    parameter_space = [dict(item) for item in profile.get("parameter_space", [])
                       if item["name"] in eligible]
    if not parameter_space:
        raise ValueError(f"parameter calibration left no live knobs for {platform}")
    # Unverified knobs are removed from the *search* domain, not silently
    # deleted from the effective flow configuration.  They remain fixed at
    # the server-owned baseline so every arm sees the same non-search values.
    baseline = dict(profile.get("baseline", {}))
    search_baseline = {name: value for name, value in baseline.items()
                       if name in eligible}
    fixed_parameters = {name: value for name, value in baseline.items()
                        if name not in eligible}
    excluded = [{"name": name,
                 "classification": (by_name.get(name) or {}).get("classification", "not_calibrated")}
                for name in sorted(declared - eligible)]
    return {
        **dict(profile),
        "baseline": baseline,
        "search_baseline": search_baseline,
        "fixed_parameters": fixed_parameters,
        "parameter_space": parameter_space,
        "parameter_calibration": {
            "protocol": report["protocol"],
            "search_eligible": sorted(eligible),
            "excluded": excluded,
            "evaluation_count": report.get("evaluation_count"),
            "claim_boundary": report.get("claim_boundary"),
        },
        "claim_boundary": (
            "Search space is filtered by controlled GCD transport/liveness evidence on the "
            "pinned ORFS toolchain. Design-specific feasibility remains learned from failed "
            "full runs and is not implied by this calibration."
        ),
    }


def apply_parameter_search_allowlist(
    profile: Mapping[str, Any], allowed_names: set[str] | frozenset[str], *,
    domain_id: str,
) -> dict[str, Any]:
    """Apply a second, subtractive paper-fairness search-domain gate."""
    allowed = set(allowed_names)
    declared = {str(item["name"]) for item in profile.get("parameter_space", [])}
    unknown = sorted(allowed - declared)
    if unknown:
        raise ValueError(f"search allowlist contains undeclared parameters: {', '.join(unknown)}")
    selected = declared & allowed
    if not selected:
        raise ValueError("search allowlist leaves no parameters")
    parameter_space = [dict(item) for item in profile["parameter_space"]
                       if item["name"] in selected]
    baseline = dict(profile.get("baseline", {}))
    calibration = dict(profile.get("parameter_calibration") or {})
    liveness_eligible = sorted(calibration.get("search_eligible") or declared)
    fixed = {**dict(profile.get("fixed_parameters", {})),
             **{name: value for name, value in baseline.items() if name not in selected}}
    return {
        **dict(profile),
        "parameter_space": parameter_space,
        "search_baseline": {name: baseline[name] for name in selected},
        "fixed_parameters": dict(sorted(fixed.items())),
        "parameter_calibration": {
            **calibration,
            "liveness_search_eligible": liveness_eligible,
            "search_eligible": sorted(selected),
            "paper_domain_excluded": sorted(declared - selected),
        },
        "search_domain": {
            "domain_id": domain_id,
            "selected": sorted(selected),
            "excluded": sorted(declared - selected),
            "subtractive_only": True,
        },
        "claim_boundary": (
            f"Search is restricted to the server-owned subtractive domain {domain_id}; "
            "all excluded calibrated parameters remain fixed at baseline values."
        ),
    }


def official_autotuner_common_parameter_names(
    profile: Mapping[str, Any], variables_yaml: str | Path,
) -> set[str]:
    """Return the calibrated intersection with pinned AutoTuner tunables."""
    import yaml
    path = Path(variables_yaml).expanduser().resolve()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    officially_tunable = {str(name) for name, row in data.items()
                          if isinstance(row, dict) and row.get("tunable", 0) == 1}
    return {str(item["name"]) for item in profile.get("parameter_space", [])
            if ORFS_PARAMETER_BY_NAME[str(item["name"])].env_name in officially_tunable}


def official_autotuner_independent_parameter_names(
    profile: Mapping[str, Any], variables_yaml: str | Path,
) -> set[str]:
    """Return the fair AutoTuner domain representable by every compared arm.

    The pinned upstream AutoTuner can express independent ranges for Hyperopt,
    but cannot express cross-parameter conditions (its conditional padding
    sampler is implemented only for random search).  Native optimizers project
    such samples into the legal typed space.  Letting Hyperopt sample the raw
    Cartesian product would therefore charge it for configurations that native
    arms can never propose.  We remove only the dependent variable and keep it
    fixed at the calibrated baseline; its independent target remains tunable
    when the fixed value satisfies the target's complete range.
    """
    common = official_autotuner_common_parameter_names(profile, variables_yaml)
    specs = {str(item["name"]): item for item in profile.get("parameter_space", [])}
    baseline = dict(profile.get("baseline") or {})
    selected = set(common)
    for name in sorted(common):
        relation = specs[name].get("less_than_or_equal_to")
        if not relation:
            continue
        target = specs.get(str(relation))
        if target is None:
            raise ValueError(f"relational target is absent from profile: {relation}")
        fixed_value = baseline.get(name)
        target_lower = target.get("lower")
        if fixed_value is None or target_lower is None or float(fixed_value) > float(target_lower):
            raise ValueError(
                f"cannot fix {name} while searching {relation} without changing the legal domain"
            )
        selected.remove(name)
    if not selected:
        raise ValueError("independent official AutoTuner common domain is empty")
    return selected
