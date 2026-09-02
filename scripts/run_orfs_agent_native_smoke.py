#!/usr/bin/env python3
"""Run the pinned upstream GP/EI workbench without its remote/LLM launcher.

This admission smoke executes the upstream Python entrypoint only.  It neither
starts SSH, runs ORFS, writes upstream source, nor uses an Anthropic credential.
The platform adapter smoke is separate evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


COMMIT = "730f1fa11f9c17c0aaac332412af2b2538f42e9b"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _command(*args: str) -> str:
    completed = subprocess.run(args, text=True, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, check=False)
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or "command failed")
    return completed.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.expanduser().resolve()
    workbench_dir = source / "AutoTuner-integration/ORFS-with-AutoTuner"
    if args.output.exists():
        raise FileExistsError(args.output)
    if _command("git", "-C", str(source), "rev-parse", "HEAD") != COMMIT:
        raise ValueError("source commit does not match the admitted lock")
    if _command("git", "-C", str(source), "status", "--porcelain=v1", "--untracked-files=all"):
        raise ValueError("native smoke requires a clean detached source checkout")
    if os.environ.get("ANTHROPIC_API_KEY"):
        raise ValueError("native smoke must not receive an Anthropic credential")
    if not (workbench_dir / "analyst_agent_workbench.py").is_file():
        raise FileNotFoundError("upstream workbench is missing")

    # The unmodified upstream function reads constraints.json from CWD.
    os.chdir(workbench_dir)
    sys.path.insert(0, str(workbench_dir))
    import numpy as np
    import pandas as pd
    import analyst_agent_workbench as upstream

    np.random.seed(20260902)
    rows = [
        {"CLK": 5.0, "UTIL": 40, "TNS_End_Percent": 80, "GP_PAD": 1,
         "DP_PAD": 1, "DPO": 1, "PIN_ADJ": .30, "UP_ADJ": .30,
         "LB_ADDON": .20, "HIER_SYNTH": 0, "CTS_CSIZE": 20,
         "CTS_CDIA": 90, "native_smoke_objective": 1.0},
        {"CLK": 6.0, "UTIL": 45, "TNS_End_Percent": 90, "GP_PAD": 2,
         "DP_PAD": 1, "DPO": 0, "PIN_ADJ": .40, "UP_ADJ": .40,
         "LB_ADDON": .30, "HIER_SYNTH": 1, "CTS_CSIZE": 24,
         "CTS_CDIA": 100, "native_smoke_objective": 1.2},
    ]
    frame = pd.DataFrame(rows)
    upstream.set_logger(lambda _message: None)
    upstream.initialize_tools_data(frame)
    upstream.store_all_valid_runs_df(frame)
    upstream.TOOL_STATE["pdk"] = "sky130hd"
    upstream.TOOL_STATE["circuit"] = "native-smoke"
    result = upstream.suggest_bayesian_optimization_configs(
        "native_smoke_objective", n_suggestions=1,
    )
    suggestions = result.get("suggested_configurations") if isinstance(result, dict) else None
    if not isinstance(suggestions, list) or len(suggestions) != 1:
        raise RuntimeError(f"upstream GP/EI produced no suggestion: {result!r}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({
        "schema_version": 1,
        "claim_boundary": "native upstream GP/EI entrypoint smoke; no SSH, ORFS run, network, or credential use",
        "source": {"commit": COMMIT, "license_sha256": _sha256(source / "LICENSE"),
                   "workbench_sha256": _sha256(workbench_dir / "analyst_agent_workbench.py")},
        "input_rows": len(rows), "result": result,
    }, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
