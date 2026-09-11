#!/usr/bin/env python3
"""Invoke the pinned upstream ORFS-Agent initializer on the full typed domain."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

HERE = Path(__file__).resolve().parent
PARAMETER_MAP = {
    "core_util": "UTIL", "cell_pad_global": "GP_PAD",
    "cell_pad_detail": "DP_PAD", "synth_flatten": "HIER_SYNTH",
    "pin_layer": "PIN_ADJ", "above_layer": "UP_ADJ",
    "tns": "TNS_End_Percent", "lb_addon": "LB_ADDON",
    "cts_size": "CTS_CSIZE", "cts_diameter": "CTS_CDIA",
    "enable_dpo": "DPO", "clk_period": "CLK",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write(path: Path, value: Any, *, sort_keys: bool = True) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=sort_keys), encoding="utf-8")


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load upstream initializer: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _result(*, status: str, code: int, started: str, artifacts=(), failure=None,
            provenance=None) -> dict[str, Any]:
    return {"schema_version": 1, "status": status, "exit_code": code,
            "started_at": started, "ended_at": _now(), "metrics": [],
            "artifacts": list(artifacts), "failure": failure,
            "provenance": dict(provenance or {})}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args(); started = _now()
    try:
        request = json.loads(args.request.read_text(encoding="utf-8"))
        task, plugin = request["task"], request.get("plugin", {})
        inputs = task.get("inputs")
        if (plugin.get("plugin_id") != "orfs-agent" or task.get("plugin_id") != "orfs-agent"
                or not isinstance(inputs, Mapping)
                or inputs.get("mode") != "upstream_full_initialize"):
            raise ValueError("request is not for full ORFS-Agent initialization")
        from orfs_agent_adapter import _load_protocol_receipt
        from orfs_agent_paper_policy_adapter import _source, _validate_domain, _candidate
        source, source_receipt = _source()
        domain = inputs.get("parameter_domain")
        if not isinstance(domain, Mapping):
            raise ValueError("full initialization requires a typed parameter_domain")
        design, platform, objective = (str(inputs.get(key, ""))
                                       for key in ("design", "platform", "objective"))
        _validate_domain(domain, source=source, design=design, platform=platform,
                         objective=objective, observations=[])
        if dict(_load_protocol_receipt(args.result.parent)) != dict(domain["experiment_protocol"]):
            raise ValueError("initializer protocol does not match Runtime receipt")
        count, seed = inputs.get("count"), inputs.get("initialization_seed")
        if (isinstance(count, bool) or not isinstance(count, int) or not 2 <= count <= 512
                or isinstance(seed, bool) or not isinstance(seed, int) or seed < 0):
            raise ValueError("initializer count or seed is invalid")

        upstream_source = source / "optimize.py"
        private_source = args.result.parent / "upstream_optimize_compat.py"
        original = upstream_source.read_text(encoding="utf-8")
        credential_anchor = "        api_key = #PUT YOUR KEY HERE\n"
        analysis_import_anchor = (
            "from inspectfuncs import *\n"
            "from modelfuncs import *\n"
            "from agglomfuncs import *\n"
        )
        if original.count(credential_anchor) != 1:
            raise ValueError("upstream initializer credential-placeholder anchor is absent or ambiguous")
        if original.count(analysis_import_anchor) != 1:
            raise ValueError("upstream initializer analysis-import anchor is absent or ambiguous")
        patched = original.replace(
            credential_anchor,
            "        api_key = None  # Runtime compatibility: initializer never calls LLM\n",
        ).replace(
            analysis_import_anchor,
            "# Runtime compatibility: generate_initial_parameters does not use the optional\n"
            "# analysis modules; do not import their undeclared networkx dependency here.\n",
        )
        private_source.write_text(patched, encoding="utf-8")
        sys.path.insert(0, str(source))
        try:
            upstream = _load(private_source, "orfs_agent_upstream_initializer")
        finally:
            sys.path.remove(str(source))
        workflow = upstream.OptimizationWorkflow.__new__(upstream.OptimizationWorkflow)
        workflow.parameter_names = list(PARAMETER_MAP)
        workflow.param_constraints = {}
        for local, published in PARAMETER_MAP.items():
            rule = domain["constraints"][published]
            if rule["type"] == "binary":
                workflow.param_constraints[local] = {"type": "int", "range": [0, 1]}
            else:
                workflow.param_constraints[local] = {
                    "type": "int" if rule["type"] == "integer" else "float",
                    "range": list(rule["range"]),
                }
        captured: list[dict[str, Any]] = []
        workflow._write_params_to_csv = types.MethodType(
            lambda _self, rows: captured.extend(dict(row) for row in rows), workflow)
        upstream.random.seed(seed)
        workflow.generate_initial_parameters(count)
        candidates = []
        for row in captured:
            projected = {published: row[local] for local, published in PARAMETER_MAP.items()}
            candidate = {name: projected[name] for name in domain["parameter_names"]}
            candidates.append(_candidate(candidate, platform=platform))
        if len(candidates) != count:
            raise RuntimeError("upstream initializer did not return the requested candidate count")

        root = args.result.parent.resolve()
        candidate_path = root / "initial_candidates.json"
        trace_path = root / "initialization_trace.json"
        source_path = root / "initialization_source_lock.json"
        initializer = source / "optimize.py"
        # Parameter order is part of the public 12-D contract and the upstream
        # GP feature order; do not alphabetize this artifact.
        _write(candidate_path, candidates, sort_keys=False)
        _write(trace_path, {
            "algorithm_owner": "upstream ORFS-Agent",
            "entrypoint": "OptimizationWorkflow.generate_initial_parameters",
            "source_sha256": hashlib.sha256(initializer.read_bytes()).hexdigest(),
            "private_compatibility_patch": {
                "path": private_source.name,
                "before_sha256": hashlib.sha256(original.encode()).hexdigest(),
                "after_sha256": hashlib.sha256(patched.encode()).hexdigest(),
                "changes": [
                    "make the committed empty API-key placeholder parseable",
                    "skip optional analysis-module imports whose symbols are not referenced by generate_initial_parameters",
                ],
                "scope": "Runtime-private copy only; initialization invokes the unchanged upstream method body and never calls the LLM or analysis paths",
            },
            "seed": seed, "count": count, "parameter_map": PARAMETER_MAP,
            "domain_sha256": domain["domain_sha256"],
        })
        _write(source_path, source_receipt)
        artifacts = (
            {"kind": "optimizer_candidates", "path": candidate_path.name},
            {"kind": "optimizer_trace", "path": trace_path.name},
            {"kind": "upstream_source_lock", "path": source_path.name},
        )
        args.result.write_text(json.dumps(_result(
            status="succeeded", code=0, started=started, artifacts=artifacts,
            provenance={"adapter": "orfs-agent-full-upstream-initializer",
                        **source_receipt}), indent=2), encoding="utf-8")
        return 0
    except Exception as exc:
        args.result.write_text(json.dumps(_result(
            status="failed", code=2, started=started,
            provenance={"adapter": "orfs-agent-full-upstream-initializer"},
            failure={"category": "adapter_error", "message": str(exc)}),
            indent=2), encoding="utf-8")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
