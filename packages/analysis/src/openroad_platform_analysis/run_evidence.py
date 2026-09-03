"""Build reproducible run manifests, metric provenance, and stage deltas."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import uuid
from datetime import datetime
from pathlib import Path

from openroad_platform_analysis.parsers import stage_json
from openroad_platform_analysis.graybox import build_graybox_evidence

STAGE_ORDER = ("synth", "floorplan", "place", "cts", "route", "finish")


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _version(cmd: list[str]) -> str | None:
    try:
        result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=15)
        line = next((line.strip() for line in result.stdout.splitlines() if line.strip()), "")
        return line or None
    except Exception:
        return None


def _write_json(path: Path, payload) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _metric_sources(workdir: Path, platform: str, design: str, metrics: dict) -> dict:
    base = workdir / "logs" / platform / design / "base"
    sources = {stage: {} for stage in STAGE_ORDER}
    for stage, specs in stage_json.METRIC_SPECS.items():
        wanted = set((metrics.get("stages", {}).get(stage, {}).get("metrics") or {}).keys())
        if not wanted:
            continue
        prefixes = stage_json.STAGE_FILES[stage]
        for path in sorted(base.glob("*.json")):
            if not any(path.name.startswith(prefix) for prefix in prefixes):
                continue
            try:
                raw = json.loads(path.read_text(errors="replace"))
            except (OSError, ValueError):
                continue
            for metric, candidates in specs:
                if metric not in wanted or metric in sources[stage]:
                    continue
                for raw_key in raw:
                    stripped = stage_json._strip_ns(raw_key)
                    if any(stripped == cand or stripped.endswith(cand) for cand in candidates):
                        sources[stage][metric] = {
                            "file": str(path.relative_to(workdir)),
                            "raw_key": raw_key,
                            "method": "orfs_json",
                        }
                        break
    return sources


def _stage_deltas(metrics: dict) -> dict:
    completed = [(stage, metrics["stages"][stage]["metrics"])
                 for stage in STAGE_ORDER
                 if metrics.get("stages", {}).get(stage, {}).get("status") == "completed"]
    transitions = []
    for (left_name, left), (right_name, right) in zip(completed, completed[1:]):
        changes = {}
        for key in sorted(set(left) & set(right)):
            lv, rv = left[key], right[key]
            if isinstance(lv, (int, float)) and isinstance(rv, (int, float)):
                changes[key] = {"before": lv, "after": rv, "delta": round(rv - lv, 6)}
        transitions.append({"from": left_name, "to": right_name, "metrics": changes})
    return {"stage_order": list(STAGE_ORDER), "transitions": transitions}


def _effective_parameters(workdir: Path, platform: str, design: str,
                          requested: dict) -> dict:
    effective = dict(requested)
    config = workdir / "designs" / platform / design / "config.mk"
    parameter_contract = workdir / "parameter_contract.json"
    contract = {}
    if parameter_contract.is_file():
        try:
            contract = json.loads(parameter_contract.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            contract = {}
    if config.is_file():
        text = config.read_text(errors="replace")
        for env_name, key in (("CORE_UTILIZATION", "core_utilization_pct"),
                              ("PLACE_DENSITY", "place_density")):
            match = re.search(rf"^\s*export\s+{env_name}\s*=\s*([^#\s]+)", text, re.M)
            if match:
                try:
                    effective[key] = float(match.group(1))
                except ValueError:
                    effective[key] = match.group(1)
        definitions = ((contract.get("registry") or {}).get("parameters") or [])
        for definition in definitions:
            name, env_name = definition.get("name"), definition.get("env_name")
            if name not in (contract.get("requested_parameters") or {}) or not env_name:
                continue
            match = re.search(rf"^\s*export\s+{re.escape(env_name)}\s*=\s*([^#\s]+)", text, re.M)
            if not match:
                continue
            raw = match.group(1)
            try:
                value = float(raw)
                effective[name] = int(value) if value.is_integer() else value
            except ValueError:
                effective[name] = raw
    place_log = workdir / "logs" / platform / design / "base" / "3_3_place_gp.log"
    if place_log.is_file():
        text = place_log.read_text(errors="replace")
        match = re.search(r"Placement target density:\s*([\d.]+)", text)
        if match:
            effective["openroad_place_density"] = float(match.group(1))
        match = re.search(r"Minimum Feasible Density\s+([\d.]+)", text)
        if match:
            effective["minimum_feasible_density"] = float(match.group(1))
    return effective


def _parameter_liveness(workdir: Path, effective: dict) -> dict:
    path = workdir / "parameter_contract.json"
    if not path.is_file():
        return {"schema_version": 1, "status": "legacy_unregistered",
                "parameters": [], "claim_boundary": "no typed parameter contract"}
    try:
        contract = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"schema_version": 1, "status": "invalid_contract",
                "error": str(exc), "parameters": []}
    definitions = {item["name"]: item for item in
                   (contract.get("registry") or {}).get("parameters", [])}
    rule_version = (contract.get("registry") or {}).get("liveness_rule_version") \
        or "legacy-unversioned"
    source_evidence = {item.get("name"): item for item in contract.get("source_evidence", [])}
    stage_numbers = {"floorplan": "2", "place": "3", "cts": "4", "route": "5", "finish": "6"}
    log_parts = []
    for log in (workdir / "logs").rglob("*.log") if (workdir / "logs").is_dir() else ():
        try:
            log_parts.append(log.read_text(errors="replace")[-2_000_000:])
        except OSError:
            pass
    log_text = "\n".join(log_parts)
    rows = []
    for name, requested in (contract.get("requested_parameters") or {}).items():
        materialized = effective.get(name)
        source = source_evidence.get(name) or {}
        stage = (definitions.get(name) or {}).get("stage")
        prefix = stage_numbers.get(stage)
        stage_completed = bool(prefix and any(
            (workdir / "results").glob(f"*/*/base/{prefix}_*.odb")
        ))
        value_text = f"{materialized:g}" if isinstance(materialized, (int, float)) else str(materialized)
        runtime_observed = any(re.search(
            pattern.replace("{value}", re.escape(value_text)), log_text,
        ) for pattern in source.get("runtime_patterns", ()))
        match = materialized == requested
        if runtime_observed:
            level = "runtime_value_observed"
        elif match and source.get("consumer_declared") and stage_completed:
            level = "consumer_stage_completed"
        elif match:
            level = "config_materialized"
        else:
            level = "missing"
        rows.append({
            "name": name, "env_name": (definitions.get(name) or {}).get("env_name"),
            "requested": requested, "materialized": materialized,
            "materialized_match": match,
            "consumer_declared": bool(source.get("consumer_declared")),
            "consumer_sha256": source.get("consumer_sha256"),
            "stage": stage, "stage_completed": stage_completed,
            "runtime_observed": runtime_observed,
            "evidence_level": level,
        })
    return {
        "schema_version": 1,
        "liveness_rule_version": rule_version,
        "status": "materialized" if rows and all(row["materialized_match"] for row in rows)
                  else "empty" if not rows else "mismatch",
        "effective_configuration_id": contract.get("effective_configuration_id"),
        "parameters": rows,
        "claim_boundary": "runtime_value_observed is strongest; consumer_stage_completed proves the pinned consumer and stage ran but not the exact internal numeric use",
    }


def write_run_evidence(workdir: str | Path, *, platform: str, design: str,
                       rtl_path: str | Path, requested_parameters: dict,
                       engine: str, strategy: str, status: str,
                       runtime_seconds: float | None = None,
                       stage_records: list[dict] | None = None,
                       execution_command: list[str] | None = None,
                       orfs_root: str | Path | None = None,
                       openroad_bin: str | Path | None = None,
                       yosys_bin: str | Path | None = None,
                       or_seed: int | None = None) -> dict:
    workdir = Path(workdir).resolve()
    rtl_path = Path(rtl_path).resolve()
    analysis_dir = workdir / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)

    expected_stage = stage_records[-1]["stage"] if stage_records else "finish"
    metrics = stage_json.extract_metrics(workdir, platform, design,
                                         expected_stage=expected_stage)
    sources = _metric_sources(workdir, platform, design, metrics)
    for stage, stage_sources in sources.items():
        if stage in metrics.get("stages", {}):
            metrics["stages"][stage]["sources"] = stage_sources
    effective = _effective_parameters(workdir, platform, design, requested_parameters)
    parameter_liveness = _parameter_liveness(workdir, effective)

    config_path = workdir / "designs" / platform / design / "config.mk"
    project_root = Path(__file__).resolve().parent.parent
    experiment_id = f"{workdir.name}-{hashlib.sha256(str(workdir).encode()).hexdigest()[:8]}"
    resolved_orfs_root = Path(orfs_root or Path.home() / "OpenROAD-flow-scripts").expanduser().resolve()
    platform_config = resolved_orfs_root / "flow" / "platforms" / platform / "config.mk"
    manifest = {
        "schema_version": 2,
        "experiment_id": experiment_id,
        "run_id": workdir.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "design": design,
        "platform": platform,
        "engine": engine,
        "strategy": strategy,
        "status": status,
        "runtime_seconds": runtime_seconds,
        "target_stage": expected_stage,
        "random_seed": {
            "value": or_seed,
            "status": "controlled" if or_seed is not None else "not_exposed",
        },
        "inputs": {"rtl": str(rtl_path), "rtl_sha256": _sha256(rtl_path)},
        "requested_parameters": requested_parameters,
        "effective_parameters": effective,
        "parameter_liveness": parameter_liveness,
        "tools": {
            "openroad": _version([str(openroad_bin or Path.home() / "bin/openroad"), "-version"]),
            "yosys": _version([str(yosys_bin or Path.home() / "bin/yosys"), "-V"]),
            "orfs_commit": _version(["git", "-C", str(resolved_orfs_root),
                                      "rev-parse", "HEAD"]),
        },
        "platform_provenance": {
            "orfs_platform_config": str(platform_config),
            "orfs_platform_config_sha256": _sha256(platform_config),
            "pdk_version": None,
            "pdk_version_status": "not_declared_by_platform",
        },
        "execution": {"command": execution_command or [], "cwd": str(project_root),
                      "engine": engine},
        "config": {"path": str(config_path), "sha256": _sha256(config_path),
                   "content": config_path.read_text(errors="replace") if config_path.is_file() else None},
        "stages": stage_records or [],
    }
    deltas = _stage_deltas(metrics)
    chain = {
        "parameter": "PLACE_DENSITY",
        "requested": requested_parameters.get("place_density"),
        "effective": effective.get("openroad_place_density", effective.get("place_density")),
        "minimum_feasible_density": effective.get("minimum_feasible_density"),
        "steps": [
            {"layer": "Web/API", "value": requested_parameters.get("place_density"),
             "location": "web-demo/app.py:/api/run_rtl2gds"},
            {"layer": "CLI", "value": requested_parameters.get("place_density"),
             "location": "rtl_to_gds.py:--place-density"},
            {"layer": "ORFS config", "value": effective.get("place_density"),
             "location": str(config_path)},
            {"layer": "Tcl", "value": effective.get("openroad_place_density"),
             "location": "flow/scripts/global_place.tcl:global_placement -density"},
            {"layer": "Database", "value": "3_place.odb",
             "location": f"results/{platform}/{design}/base/3_place.odb"},
        ],
    }
    evidence = {
        "schema_version": 1,
        "observations": [],
        "parameter_changes": {"requested": requested_parameters, "effective": effective},
        "stage_deltas": deltas["transitions"],
        "parameter_chain": chain,
        "missing_evidence": [
            {"stage": stage, "metric": metric}
            for stage, data in metrics.get("stages", {}).items()
            for metric in ("estimated_wirelength_um", "setup_wns_ns", "congestion_overflow")
            if data.get("status") == "completed" and metric not in data.get("metrics", {})
        ],
    }
    outputs = {"run_manifest.json": manifest, "stage_metrics.json": metrics,
               "stage_deltas.json": deltas, "causal_evidence.json": evidence}
    outputs["parameter_liveness.json"] = parameter_liveness
    for filename, payload in outputs.items():
        _write_json(analysis_dir / filename, payload)

    graybox = build_graybox_evidence(
        workdir, project_root=project_root, orfs_root=resolved_orfs_root,
        manifest=manifest, metrics=metrics, requested_parameters=requested_parameters,
        effective_parameters=effective,
    )
    extra_outputs = {
        "graybox.json": graybox["graybox"],
        "parameter_provenance.json": {"schema_version": 2, "experiment_id": experiment_id,
                                      "parameters": graybox["parameters"]},
        "artifact_registry.json": {"schema_version": 2, "experiment_id": experiment_id,
                                   "artifacts": graybox["artifacts"]},
        "log_events.json": {"schema_version": 2, "experiment_id": experiment_id,
                            "events": graybox["events"]},
        "evaluation.json": graybox["evaluation"],
    }
    manifest.update({
        "environment": graybox["environment"],
        "place_substages": graybox["stage_substages"]["place"],
        "stage_substages": graybox["stage_substages"],
        "artifacts": {"registry": str(analysis_dir / "artifact_registry.json"),
                      "count": len(graybox["artifacts"])},
        "evaluation": graybox["evaluation"],
        "reproducibility": {
            "status": "partial" if manifest["random_seed"]["value"] is None or
                      manifest["platform_provenance"]["pdk_version"] is None else "complete",
            "missing": [name for name, missing in (
                ("random_seed", manifest["random_seed"]["value"] is None),
                ("pdk_version", manifest["platform_provenance"]["pdk_version"] is None),
            ) if missing],
        },
    })
    evidence["graybox_files"] = {name: str(analysis_dir / name) for name in extra_outputs}
    _write_json(analysis_dir / "run_manifest.json", manifest)
    _write_json(analysis_dir / "causal_evidence.json", evidence)
    for filename, payload in extra_outputs.items():
        _write_json(analysis_dir / filename, payload)
    outputs.update(extra_outputs)
    return {"manifest": manifest, "metrics": metrics, "deltas": deltas,
            "evidence": evidence, "graybox": graybox,
            "paths": {name: str(analysis_dir / name) for name in outputs}}
