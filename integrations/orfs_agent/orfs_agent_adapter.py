#!/usr/bin/env python3
"""Dataset-only bridge for the pinned external ORFS-Agent project.

This adapter does not import or execute upstream optimizer code. It translates
Runtime-owned measured observations into the upstream's documented flat data
shape, preserving evidence references for a later native invocation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

INTEGRATION = Path(__file__).resolve().parent
LOCK_PATH = INTEGRATION / "source.lock.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_lock() -> dict[str, Any]:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    if lock.get("plugin_id") != "orfs-agent" or not isinstance(lock.get("commit"), str):
        raise ValueError("invalid ORFS-Agent source lock")
    return lock


def _checked_source(lock: Mapping[str, Any]) -> dict[str, str]:
    """Return immutable source identity; audit caches and branches are rejected."""
    configured = os.environ.get("ORFS_AGENT_SOURCE")
    if not configured:
        raise ValueError("ORFS_AGENT_SOURCE must name an explicit clean detached checkout")
    source = Path(configured).expanduser().resolve()
    cache = (INTEGRATION.parents[1] / str(lock["cache_path"])).resolve()
    if source == cache:
        raise ValueError("ORFS_AGENT_SOURCE must not use the source-audit cache")
    if not source.is_dir():
        raise FileNotFoundError(f"ORFS-Agent source is absent: {source}")
    git = ("git", "-C", str(source))
    head = subprocess.check_output((*git, "rev-parse", "HEAD"), text=True).strip()
    if head != lock["commit"]:
        raise ValueError("ORFS-Agent source commit does not match source lock")
    if subprocess.run((*git, "symbolic-ref", "-q", "HEAD"), stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL, check=False).returncode == 0:
        raise ValueError("ORFS_AGENT_SOURCE must be a detached checkout")
    dirty = subprocess.check_output((*git, "status", "--porcelain", "--untracked-files=all"), text=True)
    if dirty:
        raise ValueError("ORFS_AGENT_SOURCE must be clean, including untracked files")
    license_path = source / "LICENSE"
    if not license_path.is_file() or "BSD 3-Clause License" not in license_path.read_text(encoding="utf-8"):
        raise ValueError("ORFS-Agent BSD-3-Clause license check failed")
    return {"repository": str(lock["repository"]), "commit": head, "license": str(lock["license"]),
            "source_lock_sha256": _sha256(LOCK_PATH)}


def _numeric(value: Any) -> int | float | None:
    return int(value) if isinstance(value, bool) else value if isinstance(value, (int, float)) else None


def _row(observation: Mapping[str, Any], *, design: str, platform: str) -> dict[str, Any]:
    parameters, metrics = observation.get("parameters"), observation.get("metrics")
    if not isinstance(parameters, Mapping) or not isinstance(metrics, Mapping):
        raise ValueError("every observation requires object parameters and metrics")
    result: dict[str, Any] = {"circuit": design, "pdk": platform}
    for source, target in {
        "clock_period_ns": "CLK", "core_utilization_pct": "UTIL",
        "place_density_lb_addon": "LB_ADDON", "enable_dpo": "DPO",
        "tns_end_percent": "TNS_End_Percent", "global_placement_padding": "GP_PAD",
        "detail_placement_padding": "DP_PAD", "cts_cluster_size": "CTS_CSIZE",
        "cts_cluster_diameter": "CTS_CDIA",
    }.items():
        if parameters.get(source) is not None:
            result[target] = parameters[source]
    for source, target in {
        "setup_wns_ns": "finish__timing__setup__ws", "setup_tns_ns": "finish__timing__setup__tns",
        "drc_errors": "detailedroute__route__drc_errors", "wirelength_um": "detailedroute__route__wirelength",
        "power_mw": "finish__power__total", "power_W": "finish__power__total",
        "area_um2": "finish__design__core__area",
    }.items():
        if (value := _numeric(metrics.get(source))) is not None:
            result[target] = value
    if (value := _numeric(metrics.get("optimizer_objective"))) is not None:
        result["optimizer_objective"] = value
    clk, slack = _numeric(result.get("CLK")), _numeric(result.get("finish__timing__setup__ws"))
    if clk is not None and slack is not None:
        result["ECP_final"] = float(clk) - float(slack)
    result["platform_observation_id"] = str(observation.get("observation_id") or observation.get("run_id") or "")
    result["platform_artifact_refs"] = list(observation.get("artifact_refs") or ())
    result["platform_feasible"] = bool(observation.get("feasible", False))
    return result


def _result(*, status: str, started: str, artifacts: list[dict[str, str]],
            provenance: Mapping[str, Any], failure: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {"schema_version": 1, "status": status, "exit_code": 0 if status == "succeeded" else 2,
            "started_at": started, "ended_at": _now(), "metrics": [], "artifacts": artifacts,
            "failure": failure, "provenance": dict(provenance)}


def _load_protocol_receipt(workspace: Path) -> Mapping[str, Any]:
    receipt_path = os.environ.get("ORFS_AGENT_PROTOCOL_RECEIPT")
    expected_sha256 = os.environ.get("ORFS_AGENT_PROTOCOL_RECEIPT_SHA256")
    if not receipt_path:
        raise ValueError("Runtime must inject ORFS_AGENT_PROTOCOL_RECEIPT")
    path = Path(receipt_path).resolve()
    try:
        path.relative_to(workspace.resolve())
    except ValueError as exc:
        raise ValueError("Runtime protocol receipt must be inside the attempt workspace") from exc
    content = path.read_bytes()
    if not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256) or hashlib.sha256(content).hexdigest() != expected_sha256:
        raise ValueError("Runtime protocol receipt digest does not match")
    receipt = json.loads(content)
    if not isinstance(receipt, Mapping) or set(receipt) != {"schema_version", "protocol", "run_id", "attempt_id"} or receipt.get("schema_version") != 1:
        raise ValueError("Runtime protocol receipt is invalid")
    if not isinstance(receipt["protocol"], Mapping):
        raise ValueError("Runtime protocol receipt is invalid")
    return receipt["protocol"]


def _validate_domain_and_observations(domain: Mapping[str, Any], observations: list[Any], platform: str,
                                      authoritative_protocol: Mapping[str, Any]) -> None:
    required = {"schema_version", "platform", "search_parameter_names", "admissible_values", "fixed_parameters",
                "experiment_protocol", "protocol_sha256", "frozen_constraints", "domain_sha256"}
    if set(domain) != required or domain.get("schema_version") != 1 or domain.get("platform") != platform:
        raise ValueError("parameter_domain has unknown or missing fields")
    unsigned = {key: value for key, value in domain.items() if key != "domain_sha256"}
    if domain.get("domain_sha256") != hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()).hexdigest():
        raise ValueError("parameter_domain hash is invalid")
    protocol = domain["experiment_protocol"]
    protocol_keys = {"rtl_sha256", "pdk_id", "toolchain_id", "sdc_sha256", "evaluator_version", "seed_policy", "timing"}
    if not isinstance(protocol, Mapping) or set(protocol) != protocol_keys or not isinstance(protocol.get("timing"), Mapping):
        raise ValueError("experiment protocol is invalid")
    if not all(isinstance(protocol[name], str) and protocol[name] for name in ("pdk_id", "toolchain_id", "evaluator_version", "seed_policy")):
        raise ValueError("experiment protocol identifiers are invalid")
    if not all(isinstance(protocol[name], str) and re.fullmatch(r"[0-9a-f]{64}", protocol[name]) for name in ("rtl_sha256", "sdc_sha256")):
        raise ValueError("experiment protocol hashes are invalid")
    protocol_hash = hashlib.sha256(json.dumps(protocol, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if dict(protocol) != dict(authoritative_protocol):
        raise ValueError("request protocol does not match Runtime protocol receipt")
    if domain.get("protocol_sha256") != protocol_hash or set(protocol["timing"]) != {"clock_period_ns", "clock_uncertainty_ns", "io_delay_ns"}:
        raise ValueError("experiment protocol hash or timing is invalid")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in protocol["timing"].values()):
        raise ValueError("experiment protocol timing is invalid")
    try:
        timing = {key: float(value) for key, value in protocol["timing"].items()}
    except (TypeError, ValueError) as exc:
        raise ValueError("experiment protocol timing is invalid") from exc
    if not all(math.isfinite(value) for value in timing.values()) or timing["clock_period_ns"] <= 0 or min(timing.values()) < 0:
        raise ValueError("experiment protocol timing is invalid")
    names = {"core_utilization_pct", "tns_end_percent", "global_placement_padding", "detail_placement_padding",
             "enable_dpo", "place_density_lb_addon", "cts_cluster_size", "cts_cluster_diameter"}
    search, fixed = domain.get("search_parameter_names"), domain.get("fixed_parameters")
    values = domain.get("admissible_values")
    if not isinstance(search, list) or set(search) | set(fixed or {}) != names or set(search) & set(fixed or {}) or set(values or {}) != set(search):
        raise ValueError("parameter_domain is not a complete allowlisted partition")
    if domain.get("frozen_constraints") != ["clock_period_ns", "clock_uncertainty_ns", "io_delay_ns"]:
        raise ValueError("parameter_domain frozen constraints are invalid")
    if platform not in {"asap7", "sky130hd", "nangate45"}:
        raise ValueError("platform is not allowlisted")
    bounds = {"core_utilization_pct": (30, 75) if platform == "asap7" else (20, 70) if platform == "sky130hd" else (20, 80),
              "tns_end_percent": (0, 100), "global_placement_padding": (0, 3), "detail_placement_padding": (0, 3),
              "enable_dpo": (0, 1), "place_density_lb_addon": (0, .5), "cts_cluster_size": (10, 40), "cts_cluster_diameter": (40, 120)}
    integers = names - {"place_density_lb_addon"}
    def canonical(name: str, value: Any) -> int | float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ValueError(f"{name} is not finite numeric")
        normalized = int(value) if name in integers else float(value)
        if normalized != value or not bounds[name][0] <= normalized <= bounds[name][1]:
            raise ValueError(f"{name} is outside its admitted range")
        return normalized
    normalized_fixed = {name: canonical(name, value) for name, value in fixed.items()}
    normalized_values = {}
    for name, raw in values.items():
        if not isinstance(raw, list):
            raise ValueError("admissible values must be lists")
        choices = tuple(dict.fromkeys(canonical(name, value) for value in raw))
        if len(choices) < 2:
            raise ValueError("every search parameter needs two admissible values")
        normalized_values[name] = choices
    if {"global_placement_padding", "detail_placement_padding"} <= set(search):
        raise ValueError("padding relation requires one padding value fixed")
    gp, dp = normalized_fixed.get("global_placement_padding"), normalized_fixed.get("detail_placement_padding")
    if gp is not None and dp is not None and dp > gp:
        raise ValueError("detail padding exceeds global padding")
    if gp is not None and "detail_placement_padding" in normalized_values and any(value > gp for value in normalized_values["detail_placement_padding"]):
        raise ValueError("detail padding domain exceeds fixed global padding")
    if dp is not None and "global_placement_padding" in normalized_values and any(value < dp for value in normalized_values["global_placement_padding"]):
        raise ValueError("global padding domain is below fixed detail padding")
    for observation in observations:
        parameters = observation.get("parameters") if isinstance(observation, Mapping) else None
        if not isinstance(parameters, Mapping) or set(parameters) != names | {"clock_period_ns"}:
            raise ValueError("observation must contain the frozen clock and complete shared domain")
        if (isinstance(parameters["clock_period_ns"], bool) or not isinstance(parameters["clock_period_ns"], (int, float))
                or observation.get("protocol_sha256") != protocol_hash or parameters["clock_period_ns"] != timing["clock_period_ns"]):
            raise ValueError("observation does not match the frozen experiment protocol")
        for name in names:
            value = canonical(name, parameters[name])
            if name in normalized_fixed and value != normalized_fixed[name]:
                raise ValueError("observation fixed parameter differs from its domain")
            if name in normalized_values and value not in normalized_values[name]:
                raise ValueError("observation search parameter is outside its domain")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args(); started = _now()
    try:
        request = json.loads(args.request.read_text(encoding="utf-8")); task = request["task"]
        if request.get("plugin", {}).get("plugin_id") != "orfs-agent" or task.get("plugin_id") != "orfs-agent":
            raise ValueError("request is not for orfs-agent")
        inputs = task.get("inputs")
        if not isinstance(inputs, Mapping):
            raise ValueError("task inputs must be an object")
        design, platform, objective = (str(inputs.get(name) or "") for name in ("design", "platform", "objective"))
        observations = inputs.get("observations")
        parameter_domain = inputs.get("parameter_domain")
        if not design or not platform or not objective or not isinstance(observations, list) or not observations:
            raise ValueError("design, platform, objective, and non-empty observations are required")
        if not all(isinstance(item, Mapping) for item in observations):
            raise ValueError("observations must be objects")
        if not isinstance(parameter_domain, Mapping):
            raise ValueError("a typed parameter_domain for the requested platform is required")
        # The dataset bridge remains the default admission boundary.  Native
        # GP/EI is an explicit, bounded mode and is delegated to the separate
        # adapter so this file never reimplements upstream search logic.
        if inputs.get("mode") == "native_agent":
            from orfs_agent_native_adapter import main as native_main
            return native_main()
        _validate_domain_and_observations(parameter_domain, observations, platform, _load_protocol_receipt(args.result.parent))
        upstream = _checked_source(_load_lock())
        rows = [_row(item, design=design, platform=platform) for item in observations]
        workspace = args.result.parent
        dataset, manifest, source_lock = (workspace / "orfs_agent_output.json", workspace / "orfs_agent_input_manifest.json",
                                          workspace / "orfs_agent_source_lock.json")
        _write(dataset, rows)
        _write(manifest, {"schema_version": 1, "kind": "orfs-agent-dataset-bridge", "task_id": task["task_id"],
                          "design": design, "platform": platform, "objective": objective, "record_count": len(rows),
                          "dataset_sha256": _sha256(dataset), "upstream": upstream,
                          "parameter_domain": dict(parameter_domain),
                          "preserved_fields": ["platform_observation_id", "platform_artifact_refs", "platform_feasible"]})
        _write(source_lock, _load_lock())
        artifacts = [{"kind": "optimizer_dataset", "path": dataset.name},
                     {"kind": "optimizer_input_manifest", "path": manifest.name},
                     {"kind": "upstream_source_lock", "path": source_lock.name}]
        args.result.write_text(json.dumps(_result(status="succeeded", started=started, artifacts=artifacts,
            provenance={"adapter": "orfs-agent-dataset-bridge", **upstream}), indent=2), encoding="utf-8")
        return 0
    except Exception as exc:
        args.result.write_text(json.dumps(_result(status="failed", started=started, artifacts=[],
            provenance={"adapter": "orfs-agent-dataset-bridge"}, failure={"category": "adapter_error", "message": str(exc)}), indent=2), encoding="utf-8")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
