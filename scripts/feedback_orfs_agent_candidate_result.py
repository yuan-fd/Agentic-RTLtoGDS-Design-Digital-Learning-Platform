#!/usr/bin/env python3
"""Feed one measured ORFS candidate result into pinned upstream ORFS-Agent GP/EI.

This utility deliberately invokes the upstream workbench entrypoint rather
than implementing a local optimizer.  It writes a new candidate proposal only
after appending an artifact-backed successful Runtime measurement to the
upstream project's own initialization data.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path


PARAMETERS = (
    "CLK", "UTIL", "TNS_End_Percent", "GP_PAD", "DP_PAD", "DPO",
    "PIN_ADJ", "UP_ADJ", "LB_ADDON", "HIER_SYNTH", "CTS_CSIZE", "CTS_CDIA",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--metrics", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--suggestions", type=int, default=1)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite feedback evidence: {args.output}")
    source = args.source.resolve()
    workbench_dir = source / "AutoTuner-integration" / "ORFS-with-AutoTuner"
    workbench = workbench_dir / "analyst_agent_workbench.py"
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    metrics = json.loads(args.metrics.read_text(encoding="utf-8"))
    if tuple(candidate) != PARAMETERS:
        raise ValueError("candidate must be the complete upstream 12-field object in upstream order")
    if not isinstance(metrics.get("ECP_final"), (int, float)):
        raise ValueError("artifact-backed candidate metrics must contain numeric ECP_final")
    import pandas as pd

    dataset = pd.read_csv(workbench_dir / "init_data" / "aes_sky130hd_sampled.csv")
    observed = dict(candidate)
    observed["ECP_final"] = metrics["ECP_final"]
    dataset = pd.concat((dataset, pd.DataFrame((observed,))), ignore_index=True)
    spec = importlib.util.spec_from_file_location("upstream_orfs_agent_workbench", workbench)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load upstream entrypoint: {workbench}")
    module = importlib.util.module_from_spec(spec)
    previous_cwd = Path.cwd()
    try:
        os.chdir(workbench_dir)  # Native entrypoint resolves constraints.json from its cwd.
        spec.loader.exec_module(module)
        module.initialize_tools_data(dataset)
        module.TOOL_STATE["pdk"] = "sky130hd"
        suggestion = module.suggest_bayesian_optimization_configs("ECP_final", n_suggestions=args.suggestions)
    finally:
        os.chdir(previous_cwd)
    if not isinstance(suggestion, dict) or not suggestion.get("suggested_configurations"):
        raise RuntimeError(f"upstream GP/EI produced no proposal: {suggestion!r}")
    result = {
        "schema_version": 1,
        "upstream_entrypoint": "AutoTuner-integration/ORFS-with-AutoTuner/analyst_agent_workbench.py:suggest_bayesian_optimization_configs",
        "target": "ECP_final",
        "successful_runtime_observation": observed,
        "initialization_dataset": str(workbench_dir / "init_data" / "aes_sky130hd_sampled.csv"),
        "dataset_rows_after_feedback": len(dataset),
        "upstream_suggestion": suggestion,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
