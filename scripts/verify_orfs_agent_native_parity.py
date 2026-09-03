#!/usr/bin/env python3
"""Verify that the ORFS-Agent adapter preserves upstream GP/EI candidates.

This is an evidence-producing parity check, not a PPA experiment.  It sends a
static, valid observation table through two paths using the *same* isolated
Python environment, constraints and random seed:

1. direct import and invocation of the pinned upstream workbench; and
2. the platform's bounded ProcessAdapter invocation.

The platform policy is replaced with a deterministic row-selection executable
for this one check.  This removes model variability while retaining the real
adapter-process boundary.  A mismatch is a hard failure: it must not be
explained away by an adapter fallback or a favourable PPA result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / ".external-src/orfs-agent-admission-20260830-vNWf4x/ORFS-Agent"
VENV_PYTHON = ROOT / ".tools/venvs/orfs-agent/bin/python"
ADAPTER = ROOT / "integrations/orfs_agent/orfs_agent_adapter.py"

for package in (ROOT / "packages/contracts/src", ROOT / "packages/execution/src"):
    sys.path.insert(0, str(package))

from openroad_platform_execution import (  # noqa: E402
    build_orfs_agent_native_task,
    orfs_agent_plugin_manifest,
)
from openroad_platform_execution.adapter import ProcessAdapter  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def _observations() -> list[dict[str, Any]]:
    """A valid, diverse upstream-domain dataset; this is not a QoR claim."""
    rows = []
    recipes = (
        (38, 72, 0, 0, 0, 0.1100, 16, 88, -1.35),
        (42, 78, 1, 0, 1, 0.1800, 20, 94, -1.10),
        (46, 82, 1, 1, 0, 0.2400, 24, 100, -0.85),
        (50, 86, 2, 1, 1, 0.3100, 28, 106, -0.60),
        (54, 90, 3, 2, 0, 0.3800, 32, 112, -0.40),
        (58, 94, 3, 3, 1, 0.4400, 36, 118, -0.25),
    )
    for index, (util, tns, gp, dp, dpo, lb, csize, cdia, wns) in enumerate(recipes):
        rows.append({
            "observation_id": f"parity-{index:02d}",
            "feasible": True,
            "artifact_refs": [f"parity://observation/{index}"],
            "parameters": {
                "clock_period_ns": 400.0,
                "core_utilization_pct": util,
                "tns_end_percent": tns,
                "global_placement_padding": gp,
                "detail_placement_padding": dp,
                "enable_dpo": dpo,
                "place_density_lb_addon": lb,
                "cts_cluster_size": csize,
                "cts_cluster_diameter": cdia,
            },
            "metrics": {
                "setup_wns_ns": wns,
                "setup_tns_ns": -10.0 - index,
                "drc_errors": 0,
                "wirelength_um": 1000.0 + 10 * index,
                "area_um2": 500.0 + 5 * index,
                "power_mw": 1.0 + .1 * index,
            },
        })
    return rows


def _fake_policy(path: Path, row_count: int) -> None:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "args = sys.argv\n"
        "output = args[args.index('--output-last-message') + 1]\n"
        f"json.dump({{'training_row_ids': list(range({row_count})), "
        "'rationale': 'deterministic parity selection', "
        "'uncertainty': 'not applicable to parity check'}, open(output, 'w'))\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _run_direct(*, root: Path, translated_rows: list[dict[str, Any]], seed: int,
                suggestions: int) -> dict[str, Any]:
    """Call the unmodified upstream function in its isolated environment."""
    direct = root / "direct"
    direct.mkdir()
    _write(direct / "rows.json", translated_rows)
    # The adapter's documented transport intersection is intentionally used
    # by both sides.  The purpose is to verify no candidate mutation at this
    # boundary, not to assert that the platform covers every paper knob.
    sys.path.insert(0, str(ROOT / "integrations/orfs_agent"))
    try:
        import orfs_agent_adapter as bridge  # type: ignore
        _write(direct / "constraints.json", bridge._shared_constraints(SOURCE, platform="asap7"))
    finally:
        sys.path.remove(str(ROOT / "integrations/orfs_agent"))
    runner = direct / "direct_upstream.py"
    runner.write_text(
        "import json, os, random, sys\n"
        "from pathlib import Path\n"
        "import numpy as np\n"
        "import pandas as pd\n"
        f"source = Path({str(SOURCE)!r})\n"
        "workspace = Path.cwd()\n"
        "sys.path.insert(0, str(source / 'AutoTuner-integration/ORFS-with-AutoTuner'))\n"
        "import analyst_agent_workbench as workbench\n"
        "workbench.set_logger(lambda _: None)\n"
        "rows = json.loads((workspace / 'rows.json').read_text())\n"
        "df = pd.DataFrame(rows)\n"
        "workbench.initialize_tools_data(df)\n"
        "workbench.store_all_valid_runs_df(df)\n"
        "workbench.TOOL_STATE['pdk'] = 'asap7'\n"
        "workbench.TOOL_STATE['circuit'] = 'parity-aes'\n"
        f"random.seed({seed})\n"
        f"np.random.seed({seed})\n"
        f"result = workbench.suggest_bayesian_optimization_configs('ECP_final', n_suggestions={suggestions})\n"
        "(workspace / 'direct-upstream-outcome.json').write_text(json.dumps(result, indent=2, sort_keys=True))\n",
        encoding="utf-8",
    )
    # The upstream checkout is an admitted immutable source, not a Python
    # cache directory.  The direct-native leg must obey the same no-write
    # source boundary as the Runtime adapter, otherwise a parity check would
    # itself invalidate the source admission for a later formal campaign.
    direct_env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    completed = subprocess.run(
        [str(VENV_PYTHON), str(runner)], cwd=direct, env=direct_env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if completed.returncode:
        raise RuntimeError("direct upstream workbench failed:\n" + completed.stderr[-4000:])
    outcome = json.loads((direct / "direct-upstream-outcome.json").read_text())
    if not isinstance(outcome, dict) or not isinstance(outcome.get("suggested_configurations"), list):
        raise RuntimeError(f"direct upstream workbench gave no candidates: {outcome}")
    return outcome


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260830)
    parser.add_argument("--suggestions", type=int, default=5)
    args = parser.parse_args()
    if not SOURCE.is_dir() or not VENV_PYTHON.is_file() or not ADAPTER.is_file():
        raise SystemExit("pinned source, isolated Python, or adapter is missing")
    root = args.output.expanduser().resolve()
    if root.exists():
        raise SystemExit(f"refusing to overwrite existing evidence directory: {root}")
    root.mkdir(parents=True)
    observations = _observations()
    _write(root / "input-observations.json", observations)

    # First materialize the exact row contract through the adapter itself;
    # direct upstream and platform paths then consume byte-identical rows.
    dataset_task = build_orfs_agent_native_task(
        project_id="orfs-agent-parity", design_id="parity-aes", platform_name="asap7",
        objective="ECP_final", observations=observations, n_suggestions=args.suggestions,
        optimizer_seed=args.seed, task_id="orfs-agent-native-parity",
    )
    policy = root / "deterministic-policy"
    _fake_policy(policy, len(observations))
    manifest = orfs_agent_plugin_manifest(SOURCE, python_executable=VENV_PYTHON)
    manifest = replace(manifest, environment={**manifest.environment,
                                                "ORFS_AGENT_CODEX_EXECUTABLE": str(policy)})
    execution = ProcessAdapter().execute(manifest, dataset_task, workspace=root / "platform")
    if execution.result.status.value != "succeeded":
        raise SystemExit(f"platform adapter failed: {execution.result.failure}")
    platform_rows = json.loads((root / "platform/orfs_agent_output.json").read_text())
    direct_outcome = _run_direct(root=root, translated_rows=platform_rows,
                                 seed=args.seed, suggestions=args.suggestions)
    trace = json.loads((root / "platform/orfs_agent_policy_trace.json").read_text())
    platform_raw = trace["upstream_outcome"].get("suggested_configurations")
    direct_raw = direct_outcome.get("suggested_configurations")
    passed = platform_raw == direct_raw
    report = {
        "schema_version": 1,
        "check": "same-input-same-seed upstream-GP-EI candidate parity",
        "status": "passed" if passed else "failed",
        "source_commit": "730f1fa11f9c17c0aaac332412af2b2538f42e9b",
        "python": str(VENV_PYTHON),
        "seed": args.seed,
        "suggestions": args.suggestions,
        "observation_row_count": len(platform_rows),
        "input_sha256": _sha256(root / "input-observations.json"),
        "translated_rows_sha256": _sha256(root / "platform/orfs_agent_output.json"),
        "direct_raw_candidates": direct_raw,
        "adapter_raw_candidates": platform_raw,
        "adapter_candidate_artifact_sha256": _sha256(root / "platform/orfs_agent_candidates.json"),
        "note": "This verifies the bounded shared-domain adapter against the unmodified upstream GP/EI core. It does not verify the upstream Anthropic analyst conversation or paper-scale PPA.",
    }
    _write(root / "parity-report.json", report)
    print(json.dumps({key: report[key] for key in ("status", "seed", "suggestions", "observation_row_count")}, sort_keys=True))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
