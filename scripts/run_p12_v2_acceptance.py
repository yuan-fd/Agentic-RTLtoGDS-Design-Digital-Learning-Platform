#!/usr/bin/env python3
"""Run the platform-owned v2 SpecIR/RTLScout acceptance chain."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from apps.api.app import ApiState


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--execute-orfs", action="store_true")
    args = parser.parse_args()
    output = args.output_root.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    state = ApiState(
        output / "platform.db", output / "uploads", ROOT.parent / "OpenROAD-flow-scripts",
        design_root=output / "designs", legacy_root=ROOT.parent / "iccad",
        runtime_db_path=output / "runtime.db", optimization_db_path=output / "optimization.db",
        load_taiwei_plugin=False,
    )
    session = state.create_spec_session({
        "message": "Design a pure combinational two-input AND gate named and2 with 1-bit inputs a and b and 1-bit output y, y=a&b, target nangate45."
    })
    (output / "spec_session.json").write_text(json.dumps(session, indent=2), encoding="utf-8")
    frozen = state.materialize_specir(session["session_id"], {"confirmed": True})
    spec_id = frozen["spec"]["spec_id"]
    (output / "specir.json").write_text(json.dumps(frozen, indent=2), encoding="utf-8")
    result = state.run_automated_rtl_pipeline(spec_id, {
        # Acceptance proves the first bounded candidate through the platform
        # gates; revision loops are a separate provider-dependent campaign.
        "execute_orfs": args.execute_orfs, "max_revisions": 0,
    })
    (output / "pipeline.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"spec_id": spec_id, "status": result.get("status"), "pipeline_id": result.get("pipeline_id")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
