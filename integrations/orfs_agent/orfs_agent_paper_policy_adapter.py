#!/usr/bin/env python3
"""Full-domain ORFS-Agent policy + upstream GP/EI proposal adapter.

This adapter does not contain a Bayesian optimiser.  It invokes the pinned
upstream ``analyst_agent_workbench.suggest_bayesian_optimization_configs``
unchanged.  The platform model is used only for the paper's analyst-policy
choice of a measured training subset; its model substitution is explicit in
the trace.  Numeric proposals always come from the upstream GP+EI code.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PARAMETERS = (
    "CLK", "UTIL", "TNS_End_Percent", "GP_PAD", "DP_PAD", "DPO",
    "PIN_ADJ", "UP_ADJ", "LB_ADDON", "HIER_SYNTH", "CTS_CSIZE", "CTS_CDIA",
)
DOMAIN_KEYS = {
    "schema_version", "kind", "design", "platform", "parameter_names",
    "constraints", "upstream_constraints_sha256", "experiment_protocol",
    "protocol_sha256", "variable_clock_semantics", "domain_sha256",
}
TARGETS = {"ECP": "ECP_final", "DWL": "detailedroute__route__wirelength", "COMBO": "Fractional_Loss_final"}
BASELINES = {
    ("aes", "asap7"): (75438.0, 459.921), ("aes", "sky130hd"): (589825.0, 4.721),
    ("ibex", "asap7"): (115285.0, 1361.547), ("ibex", "sky130hd"): (808423.0, 11.543),
    ("jpeg", "asap7"): (300326.0, 1148.04), ("jpeg", "sky130hd"): (1374966.0, 7.731),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source() -> tuple[Path, dict[str, str]]:
    root = Path(os.environ["ORFS_AGENT_SOURCE"]).expanduser().resolve()
    expected = os.environ["ORFS_AGENT_EXPECTED_COMMIT"]
    actual = subprocess.check_output(("git", "-C", str(root), "rev-parse", "HEAD"), text=True).strip()
    if actual != expected:
        raise ValueError(f"ORFS-Agent source commit mismatch: {actual} != {expected}")
    if subprocess.run(("git", "-C", str(root), "symbolic-ref", "-q", "HEAD"),
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                      check=False).returncode == 0:
        raise ValueError("ORFS-Agent execution source must be detached")
    dirty = subprocess.check_output(
        ("git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"),
        text=True,
    )
    if dirty:
        raise ValueError("ORFS-Agent execution source must be clean")
    license_path = root / "LICENSE"
    if (not license_path.is_file()
            or "BSD 3-Clause License" not in license_path.read_text(encoding="utf-8")):
        raise ValueError("ORFS-Agent BSD-3-Clause license check failed")
    return root, {"source": str(root), "commit": actual, "license": "BSD-3-Clause",
                  "license_sha256": _sha256(license_path)}


def _validate_domain(domain: Mapping[str, Any], *, source: Path, design: str,
                     platform: str, objective: str,
                     observations: list[Mapping[str, Any]]) -> None:
    """Recheck the full typed contract inside the adapter process."""
    if (set(domain) != DOMAIN_KEYS or domain.get("schema_version") != 2
            or domain.get("kind") != "upstream-full-12d"
            or domain.get("parameter_names") != list(PARAMETERS)
            or domain.get("variable_clock_semantics") is not True):
        raise ValueError("full ORFS-Agent policy requires the complete typed 12-D domain")
    canonical = {name: value for name, value in domain.items() if name != "domain_sha256"}
    if domain.get("domain_sha256") != _digest(canonical):
        raise ValueError("full ORFS-Agent domain hash is invalid")
    protocol = domain.get("experiment_protocol")
    if not isinstance(protocol, Mapping) or domain.get("protocol_sha256") != _digest(protocol):
        raise ValueError("full ORFS-Agent protocol hash is invalid")
    if (protocol.get("design") != design or protocol.get("platform") != platform
            or protocol.get("objective_set") != ["ECP", "DWL", "COMBO"]
            or objective not in protocol.get("objective_set", ())):
        raise ValueError("full ORFS-Agent protocol identity/objectives are invalid")
    constraints_path = source / "AutoTuner-integration/ORFS-with-AutoTuner/constraints.json"
    if domain.get("upstream_constraints_sha256") != _sha256(constraints_path):
        raise ValueError("full ORFS-Agent domain is not bound to upstream constraints.json")
    constraints = domain.get("constraints")
    if not isinstance(constraints, Mapping) or tuple(constraints) != PARAMETERS:
        raise ValueError("full ORFS-Agent domain reduced or reordered upstream parameters")
    for observation in observations:
        if observation.get("protocol_sha256") != domain["protocol_sha256"]:
            raise ValueError("full ORFS-Agent observation belongs to another protocol")
        candidate = observation.get("candidate")
        if not isinstance(candidate, Mapping):
            raise ValueError("full ORFS-Agent observation lacks a 12-D candidate")
        _candidate(candidate, platform=platform)


def _candidate(value: Mapping[str, Any], *, platform: str) -> dict[str, int | float]:
    # Reuse the exact paper-execution validator instead of creating a second
    # platform projection.  This loads no optimiser code.
    executor = _load_module(HERE / "orfs_agent_reproduction_adapter.py", "orfs_agent_paper_executor_contract")
    return executor.validate_candidate(value, platform=platform)


def _row(observation: Mapping[str, Any], *, design: str, platform: str, target: str) -> dict[str, Any]:
    candidate = observation.get("candidate")
    metrics = observation.get("metrics")
    if not isinstance(candidate, Mapping) or not isinstance(metrics, Mapping):
        raise ValueError("each observation requires candidate and metrics objects")
    row: dict[str, Any] = {"circuit": design, "pdk": platform,
                           **_candidate(candidate, platform=platform)}
    for key, value in metrics.items():
        if isinstance(key, str) and isinstance(value, (int, float)) and not isinstance(value, bool):
            row[key] = value
    ecp = row.get("ECP_final")
    if not isinstance(ecp, (int, float)):
        slack = row.get("finish__timing__setup__ws")
        if isinstance(slack, (int, float)):
            row["ECP_final"] = float(row["CLK"]) - float(slack)
    if target == "Fractional_Loss_final" and target not in row:
        wirelength = row.get("detailedroute__route__wirelength")
        ecp = row.get("ECP_final")
        if isinstance(wirelength, (int, float)) and isinstance(ecp, (int, float)):
            base_wl, base_ecp = BASELINES[(design, platform)]
            row[target] = float(wirelength) / base_wl + float(ecp) / base_ecp
    if not isinstance(row.get(target), (int, float)):
        raise ValueError(f"observation lacks numeric target {target}")
    return row


def _policy_rows(rows: list[dict[str, Any]], *, objective: str, suggestions: int) -> tuple[list[int], dict[str, Any]]:
    # This managed-model boundary returns only measured row ids.  It has no
    # dependency on the historical 8-D bridge and cannot emit numeric points.
    policy_module = _load_module(HERE / "orfs_agent_managed_analyst_policy.py", "orfs_agent_managed_analyst_policy")
    policy = policy_module.select_training_rows(rows, objective=objective, suggestions=suggestions)
    ids = policy["training_row_ids"]
    if not isinstance(ids, list) or len(ids) < 2:
        raise ValueError("managed model returned an invalid upstream training subset")
    return ids, policy


def _upstream_candidates(rows: list[dict[str, Any]], *, source: Path, design: str,
                         platform: str, target: str, suggestions: int, seed: int,
                         workspace: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not 1 <= suggestions <= 64 or len(rows) < 2:
        raise ValueError("upstream GP/EI needs two or more rows and 1..64 suggestions")
    try:
        import numpy as np  # type: ignore
        import pandas as pd  # type: ignore
    except ImportError as exc:
        raise RuntimeError("isolated ORFS-Agent Python dependencies are absent") from exc
    analyst = source / "AutoTuner-integration/ORFS-with-AutoTuner"
    workbench = _load_module(analyst / "analyst_agent_workbench.py", "orfs_agent_upstream_workbench")
    # Its current pdk/circuit filters and BO implementation are upstream code.
    ids, policy = _policy_rows(rows, objective=target, suggestions=suggestions)
    subset = pd.DataFrame(rows).iloc[ids].copy()
    _write(workspace / "constraints.json", json.loads((analyst / "constraints.json").read_text(encoding="utf-8")))
    previous = Path.cwd()
    try:
        os.chdir(workspace)
        random.seed(seed); np.random.seed(seed)
        workbench.set_logger(lambda _: None)
        workbench.initialize_tools_data(subset)
        workbench.store_all_valid_runs_df(subset)
        workbench.TOOL_STATE["pdk"] = platform
        workbench.TOOL_STATE["circuit"] = design
        outcome = workbench.suggest_bayesian_optimization_configs(target, n_suggestions=suggestions)
    finally:
        os.chdir(previous)
    suggestions_raw = outcome.get("suggested_configurations") if isinstance(outcome, Mapping) else None
    if not isinstance(suggestions_raw, list):
        raise RuntimeError(f"upstream ORFS-Agent GP/EI returned no candidates: {outcome}")
    candidates = [_candidate(item, platform=platform) for item in suggestions_raw if isinstance(item, Mapping)]
    if len(candidates) != len(suggestions_raw):
        raise RuntimeError("upstream GP/EI returned malformed candidate data")
    return candidates, {"target": target, "policy": policy, "training_row_ids": ids,
                        "upstream_outcome": outcome, "optimizer_seed": seed,
                        "algorithm": "pinned upstream scikit-optimize Gaussian Process + Expected Improvement",
                        "model_policy": "gpt-5.6-terra training-subset selection (explicit model-substituted reproduction)"}


def _result(*, status: str, code: int, started: str, artifacts: list[dict[str, str]],
            provenance: Mapping[str, Any], failure: Mapping[str, str] | None = None) -> dict[str, Any]:
    return {"schema_version": 1, "status": status, "exit_code": code,
            "started_at": started, "ended_at": _now(), "metrics": [],
            "artifacts": artifacts, "failure": failure, "provenance": dict(provenance)}


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--request", type=Path, required=True); parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args(); started = _now()
    try:
        request = json.loads(args.request.read_text(encoding="utf-8")); task = request["task"]
        if (request.get("plugin", {}).get("plugin_id") != "orfs-agent"
                or task.get("plugin_id") != "orfs-agent"):
            raise ValueError("request is not for the admitted ORFS-Agent plugin")
        inputs = task.get("inputs")
        if not isinstance(inputs, Mapping): raise ValueError("task inputs must be an object")
        if inputs.get("mode") != "upstream_full_policy":
            raise ValueError("request is not for the full upstream ORFS-Agent policy")
        design, platform, objective = (str(inputs.get(key, "")) for key in ("design", "platform", "objective"))
        if (design, platform) not in BASELINES or objective not in TARGETS:
            raise ValueError("unsupported paper design/platform/objective")
        observations = inputs.get("observations")
        if not isinstance(observations, list) or len(observations) < 2:
            raise ValueError("at least two measured observations are required")
        source, receipt = _source()
        domain = inputs.get("parameter_domain")
        if not isinstance(domain, Mapping):
            raise ValueError("full ORFS-Agent policy requires a typed parameter_domain")
        _validate_domain(domain, source=source, design=design, platform=platform,
                         objective=objective, observations=observations)
        target = TARGETS[objective]
        rows = [_row(item, design=design, platform=platform, target=target) for item in observations if isinstance(item, Mapping)]
        if len(rows) != len(observations): raise ValueError("observations must be objects")
        root = args.result.parent.resolve()
        _write(root / "paper_observations.json", rows)
        candidates, trace = _upstream_candidates(rows, source=source, design=design, platform=platform,
                                                 target=target, suggestions=int(inputs.get("n_suggestions", 5)),
                                                 seed=int(inputs.get("optimizer_seed", 1)), workspace=root)
        _write(root / "paper_candidates.json", candidates); _write(root / "paper_policy_trace.json", trace)
        _write(root / "paper_source_lock.json", receipt)
        artifacts = [{"kind": "optimizer_dataset", "path": "paper_observations.json"},
                     {"kind": "optimizer_candidates", "path": "paper_candidates.json"},
                     {"kind": "optimizer_trace", "path": "paper_policy_trace.json"},
                     {"kind": "upstream_source_lock", "path": "paper_source_lock.json"}]
        args.result.write_text(json.dumps(_result(status="succeeded", code=0, started=started, artifacts=artifacts,
            provenance={"adapter": "orfs-agent-paper-policy", **receipt,
                        "objective": objective, "target": target,
                        "candidate_domain": list(PARAMETERS)}), indent=2), encoding="utf-8")
        return 0
    except Exception as exc:
        args.result.write_text(json.dumps(_result(status="failed", code=2, started=started, artifacts=[],
            provenance={"adapter": "orfs-agent-paper-policy"}, failure={"category": "adapter_error", "message": str(exc)}), indent=2), encoding="utf-8")
        return 2


if __name__ == "__main__": raise SystemExit(main())
