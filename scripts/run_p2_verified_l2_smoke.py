#!/usr/bin/env python3
"""Bounded post-gate smoke for the P2 verified-RTL to external-L2 handoff.

It imports one immutable, Runtime-succeeded RTLScout-v2 run as evidence,
then uses fresh Runtime attempts for current compile/lint and frozen-oracle
simulation.  It deliberately stops after external-L2 checkpoint creation:
this verifies admission/provenance, not an optimizer QoR claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), *(str(ROOT / item) for item in (
    "packages/contracts/src", "packages/execution/src", "packages/scheduler/src", "packages/analysis/src"))]

from apps.api.app import ApiState  # noqa: E402
from openroad_platform_contracts import SpecIR, VerificationPackage  # noqa: E402

SOURCE_DB = ROOT / "var/rtlscout-codex-e2e-final3/runtime.db"
SOURCE_RUN = "dd35a2c05c9e4550a4c7ef39a90f247a"
SOURCE_DB_SHA256 = "b04a76268ac8409550c3c3de7f54200e6b8234b7b06ef48e7f5716b3df6fdf91"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def execute(state: ApiState, receipt: dict) -> str:
    run_id = receipt["run"]["run"]["run_id"]
    state.runtime.execute_once(run_id)
    state.auto_collect_terminal_run(run_id)
    return run_id


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_root.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"output must be empty: {output}")
    if not SOURCE_DB.is_file():
        raise FileNotFoundError(SOURCE_DB)
    source_db_sha256 = digest(SOURCE_DB)
    if source_db_sha256 != SOURCE_DB_SHA256:
        raise RuntimeError("historical RTLScout Runtime DB hash changed; source admission is not reproducible")
    output.mkdir(parents=True, exist_ok=True)
    runtime_db = output / "runtime.db"
    shutil.copy2(SOURCE_DB, runtime_db)
    if digest(runtime_db) != source_db_sha256:
        raise RuntimeError("copied Runtime DB hash does not match the pinned source")
    state = ApiState(output / "platform.db", output / "uploads", ROOT / "../OpenROAD-flow-scripts",
                     design_root=output / "designs", legacy_root=output / "legacy",
                     runtime_db_path=runtime_db, spec_db_path=output / "spec.db",
                     rtl_frontend_db_path=output / "rtl-frontend.db",
                     runtime_workspace_root=output / "attempts", load_taiwei_plugin=False)
    source = state.runtime_store.get_run(SOURCE_RUN)
    if source.status.value != "succeeded" or source.task_spec.plugin_id != "rtlscout":
        raise RuntimeError("source run is not a succeeded RTLScout run")
    inputs = source.task_spec.inputs
    if inputs.get("mode") != "specir-v2":
        raise RuntimeError("source run is not SpecIR-v2")
    source_view = state.runtime.describe(SOURCE_RUN)
    source_attempts = [attempt for stage in source_view["stages"] for attempt in stage["attempts"]
                       if attempt["status"] == "succeeded"]
    source_attempt = source_attempts[-1] if source_attempts else None
    source_rtl = next((item for item in (source_attempt or {}).get("artifacts", [])
                       if item["kind"] == "rtl"), None)
    if source_attempt is None or source_rtl is None:
        raise RuntimeError("pinned RTLScout run lacks a succeeded RTL artifact")
    source_workspace = Path(source_attempt["workspace"]).resolve()
    source_rtl_path = (source_workspace / source_rtl["store_key"]).resolve()
    try:
        source_rtl_path.relative_to(source_workspace)
    except ValueError as exc:
        raise RuntimeError("pinned RTLScout artifact escapes its Runtime workspace") from exc
    if not source_rtl_path.is_file() or digest(source_rtl_path) != source_rtl["sha256"]:
        raise RuntimeError("pinned RTLScout artifact is missing or hash-mismatched")
    state.rtl_frontend.add_spec(SpecIR.from_dict(inputs["spec"]))
    state.rtl_frontend.add_verification_package(VerificationPackage.from_dict(inputs["verification"]))
    candidate = state.record_rtlscout_candidate_run(SOURCE_RUN)
    spec_id, parent_id = str(inputs["spec"]["spec_id"]), str(candidate["candidate_id"])
    child = state.attach_rtl_simulation_oracle(spec_id, {
        "testbench_source": inputs["testbench_source"], "testbench_top": "tb",
        "oracle_origin": "project_existing", "oracle_reviewed_by": "p2-bounded-smoke",
    })
    candidate_id = str(child["candidate_id"])
    verify_run = execute(state, state.submit_rtl_verification(spec_id, candidate_id=candidate_id))
    sim_run = execute(state, state.submit_rtl_simulation(spec_id, {}, candidate_id=candidate_id))
    loop = state.start_external_optimizer_loop({"spec_id": spec_id, "candidate_id": candidate_id})
    lineage = state.get_rtl_lineage(spec_id)
    result = {
        "phase": "P2-verified-rtl-to-external-l2-smoke",
        "accepted": True, "source_rtlscout_run": SOURCE_RUN,
        "source_runtime_db": {"path": str(SOURCE_DB), "sha256": source_db_sha256},
        "source_runtime_record_sha256": hashlib.sha256(json.dumps(
            source_view, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "source_rtl_artifact": {"artifact_id": source_rtl["artifact_id"],
                                  "workspace": str(source_attempt["workspace"]),
                                  "store_key": source_rtl["store_key"],
                                  "path": str(source_rtl_path),
                                  "sha256": source_rtl["sha256"]},
        "spec_id": spec_id, "candidate_id": candidate_id,
        "compile_run": verify_run, "simulation_run": sim_run,
        "external_l2_pipeline_id": loop["pipeline_id"],
        "checkpoint_verified_rtl": loop["state"]["verified_rtl"],
        "checks": lineage["checks"],
        "runtime_db_sha256": digest(runtime_db),
    }
    (output / "acceptance_summary.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
