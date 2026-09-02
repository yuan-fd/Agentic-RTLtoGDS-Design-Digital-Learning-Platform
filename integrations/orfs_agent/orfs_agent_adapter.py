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
        if not design or not platform or not objective or not isinstance(observations, list) or not observations:
            raise ValueError("design, platform, objective, and non-empty observations are required")
        if not all(isinstance(item, Mapping) for item in observations):
            raise ValueError("observations must be objects")
        upstream = _checked_source(_load_lock())
        rows = [_row(item, design=design, platform=platform) for item in observations]
        workspace = args.result.parent
        dataset, manifest, source_lock = (workspace / "orfs_agent_output.json", workspace / "orfs_agent_input_manifest.json",
                                          workspace / "orfs_agent_source_lock.json")
        _write(dataset, rows)
        _write(manifest, {"schema_version": 1, "kind": "orfs-agent-dataset-bridge", "task_id": task["task_id"],
                          "design": design, "platform": platform, "objective": objective, "record_count": len(rows),
                          "dataset_sha256": _sha256(dataset), "upstream": upstream,
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
