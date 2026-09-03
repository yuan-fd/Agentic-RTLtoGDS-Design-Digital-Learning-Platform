#!/usr/bin/env python3
"""Bounded invocation of the pinned ORFS-Agent GP/EI workbench.

The upstream workbench owns GP/EI.  This adapter only supplies a complete
12-field upstream table, fixes non-product/frozen fields, and records the
projection back to the platform's admitted eight-field domain.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

from orfs_agent_adapter import (_checked_source, _load_lock, _load_protocol_receipt,
    _now, _result, _row, _validate_domain_and_observations, _write)

EXTRA_DEFAULTS = {"PIN_ADJ": .3, "UP_ADJ": .3, "HIER_SYNTH": 0}
PLATFORM_TO_UPSTREAM = {"core_utilization_pct":"UTIL", "tns_end_percent":"TNS_End_Percent",
    "global_placement_padding":"GP_PAD", "detail_placement_padding":"DP_PAD", "enable_dpo":"DPO",
    "place_density_lb_addon":"LB_ADDON", "cts_cluster_size":"CTS_CSIZE", "cts_cluster_diameter":"CTS_CDIA"}


def _complete_rows(observations: list[Mapping[str, Any]], *, design: str, platform: str,
                   objective: str, domain: Mapping[str, Any]) -> list[dict[str, Any]]:
    clock = domain["experiment_protocol"]["timing"]["clock_period_ns"]
    rows = []
    for observation in observations:
        row = _row(observation, design=design, platform=platform)
        row.update(EXTRA_DEFAULTS); row["CLK"] = clock
        row[objective] = observation.get("metrics", {}).get("optimizer_objective")
        if row[objective] is None:
            raise ValueError("native GP/EI requires a measured optimizer_objective on every observation")
        rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--request", type=Path, required=True); parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args(); started = _now()
    try:
        request = json.loads(args.request.read_text()); task = request["task"]; inputs = task["inputs"]
        if task.get("plugin_id") != "orfs-agent" or inputs.get("mode") != "native_agent":
            raise ValueError("request is not for the bounded ORFS-Agent native adapter")
        domain, observations = inputs.get("parameter_domain"), inputs.get("observations")
        if not isinstance(domain, Mapping) or not isinstance(observations, list) or len(observations) < 2:
            raise ValueError("native GP/EI requires a typed domain and at least two observations")
        _validate_domain_and_observations(domain, observations, str(inputs["platform"]),
                                          _load_protocol_receipt(args.result.parent))
        source = Path(os.environ["ORFS_AGENT_SOURCE"]).resolve(); upstream = _checked_source(_load_lock())
        root = args.result.parent; workbench = source / "AutoTuner-integration/ORFS-with-AutoTuner"
        rows = _complete_rows(observations, design=str(inputs["design"]), platform=str(inputs["platform"]), objective=str(inputs["objective"]), domain=domain)
        with tempfile.TemporaryDirectory(dir=root, prefix="upstream-gpei-") as raw:
            work = Path(raw); (work / "constraints.json").write_bytes((workbench / "constraints.json").read_bytes())
            sys.path.insert(0, str(workbench)); before = Path.cwd()
            try:
                sys.dont_write_bytecode = True; os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
                os.chdir(work); import pandas as pd; import analyst_agent_workbench as upstream_workbench
                upstream_workbench.set_logger(lambda _line: None); frame = pd.DataFrame(rows)
                upstream_workbench.initialize_tools_data(frame); upstream_workbench.store_all_valid_runs_df(frame)
                upstream_workbench.TOOL_STATE["pdk"] = str(inputs["platform"]); upstream_workbench.TOOL_STATE["circuit"] = str(inputs["design"])
                result = upstream_workbench.suggest_bayesian_optimization_configs(str(inputs["objective"]), n_suggestions=int(inputs.get("n_suggestions", 1)))
            finally:
                os.chdir(before); sys.path.remove(str(workbench))
        raw_candidates = result.get("suggested_configurations") if isinstance(result, Mapping) else None
        if not isinstance(raw_candidates, list): raise RuntimeError(f"upstream GP/EI failed: {result}")
        candidates = []
        for raw in raw_candidates:
            candidate = {name: raw[target] for name, target in PLATFORM_TO_UPSTREAM.items()}
            for name, values in domain["admissible_values"].items():
                if candidate[name] not in values:
                    raise ValueError("upstream GP/EI proposal is outside the frozen platform allowlist")
            for name, value in domain["fixed_parameters"].items():
                if candidate[name] != value:
                    raise ValueError("upstream GP/EI proposal changed a frozen platform parameter")
            candidates.append(candidate)
        candidate_path = root / "orfs_agent_candidates.json"; trace_path = root / "orfs_agent_gpei_trace.json"
        _write(candidate_path, candidates); _write(trace_path, {"algorithm":"upstream scikit-optimize GP/EI", "raw_candidates":raw_candidates, "fixed_upstream_fields":{"CLK":domain["experiment_protocol"]["timing"]["clock_period_ns"], **EXTRA_DEFAULTS}, "projection":PLATFORM_TO_UPSTREAM})
        artifacts=[{"kind":"optimizer_candidates","path":candidate_path.name},{"kind":"optimizer_trace","path":trace_path.name}]
        args.result.write_text(json.dumps(_result(status="succeeded",started=started,artifacts=artifacts,provenance={"adapter":"bounded-upstream-orfs-agent-gpei",**upstream}),indent=2)); return 0
    except Exception as exc:
        args.result.write_text(json.dumps(_result(status="failed",started=started,artifacts=[],provenance={"adapter":"bounded-upstream-orfs-agent-gpei"},failure={"category":"adapter_error","message":str(exc)}),indent=2)); return 2

if __name__ == "__main__": raise SystemExit(main())
