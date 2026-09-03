#!/usr/bin/env python3
"""Run or resume one preregistered native optimizer cell through API/Runtime."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for source in (ROOT, *sorted((ROOT / "packages").glob("*/src"))):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from apps.api.app import ApiState  # noqa: E402
from openroad_platform_analysis import validate_industrial_dse_protocol  # noqa: E402
from openroad_platform_analysis.environment_snapshot import (  # noqa: E402
    combined_python_environment, current_python_environment,
)
from openroad_platform_scheduler.local_state import LocalStateMirror  # noqa: E402
from openroad_platform_analysis.common_evaluator import SCHEMA_VERSION as EVALUATOR_SCHEMA  # noqa: E402
from openroad_platform_execution import (  # noqa: E402
    load_orfs_reference_design, validate_pinned_orfs_toolchain,
)


ARMS = {
    "random": "seeded-random-mixed-v1",
    "sobol": "sobol-scrambled-mixed-v1",
    "random_full": "seeded-random-mixed-v1",
    "sobol_full": "sobol-scrambled-mixed-v1",
    "tpe": "optuna-motpe-mixed-v1",
    "qlognehvi": "botorch-ard-matern-qlognehvi-mixed-v2",
    "portfolio": "industrial-dse-portfolio-v1",
    "stateful_portfolio": "stateful-l2-portfolio-v1",
}
ABLATIONS = (
    "none", "no_gp", "no_multifidelity", "no_feasibility",
    "no_trust_region", "no_memory", "no_stage_focus", "no_edair",
    "no_safe_initialization", "no_state_policy",
    "single_replica_error_control",
)
TERMINAL = {"completed", "diagnosis_required", "failed"}


def _atomic(path: Path, value: object) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _digest(value: object) -> str:
    """Canonical identity used to isolate node-local state between cells."""
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


def _bind_output_to_cell(output: Path, manifest: dict) -> None:
    """Prevent evidence from two protocol/evaluator versions sharing a DB."""
    path = output / "cell-manifest.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != manifest:
            raise ValueError(
                "experiment output is already bound to a different cell manifest")
        return
    preexisting = [item.name for item in output.iterdir()
                   if item.name not in {"experiment.lock"}]
    if preexisting:
        raise ValueError(
            "non-empty legacy experiment output has no cell manifest; use a new output path")
    _atomic(path, manifest)


def _controller_source_snapshot() -> dict:
    roots = (
        ROOT / "apps/api",
        ROOT / "packages/analysis/src",
        ROOT / "packages/contracts/src",
        ROOT / "packages/execution/src",
        ROOT / "packages/scheduler/src",
    )
    files = []
    for pattern in (
        "*industrial_dse*.py", "*official_autotuner*.py",
        "calibrate_orfs_parameters.py", "prepare_pinned_orfs_toolchain.py",
    ):
        files.extend(sorted((ROOT / "scripts").glob(pattern)))
    for root in roots:
        files.extend(sorted(root.rglob("*.py")))
    records = [{
        "path": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    } for path in sorted(set(files))]
    digest = hashlib.sha256(json.dumps(
        records, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    return {"digest": digest, "file_count": len(records), "files": records}


def _frozen_controller_digest(protocol: dict) -> str | None:
    """Return the controller digest sealed into a stateful study protocol."""
    snapshot = ((protocol.get("reproducibility") or {}).get("source_snapshot")
                or {})
    controller = snapshot.get("controller") if isinstance(snapshot, dict) else None
    digest = controller.get("digest") if isinstance(controller, dict) else None
    return str(digest) if isinstance(digest, str) and digest else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--orfs-root", type=Path,
                        default=ROOT / "var/toolchains/orfs-51ad1231-clean")
    parser.add_argument("--toolchain-lock", type=Path, default=
                        ROOT / "integrations/orfs/orfs-industrial-v2.lock.json")
    parser.add_argument("--calibration", type=Path, default=
                        ROOT / "var/calibration/orfs-parameters-v2/parameter_calibration_report.json")
    parser.add_argument("--protocol", type=Path, default=
                        ROOT / "studies/protocols/v2-industrial-dse-20260830-r31-stateful-l2.protocol.json")
    parser.add_argument("--mode", choices=("preflight", "paper"), default="paper")
    parser.add_argument("--platform", choices=("asap7", "sky130hd"), required=True)
    parser.add_argument("--design", choices=("aes", "jpeg", "ibex"), required=True)
    parser.add_argument("--arm", choices=tuple(ARMS), required=True)
    parser.add_argument("--ablation", choices=ABLATIONS, default="none")
    parser.add_argument("--budget", type=int, required=True)
    parser.add_argument("--optimizer-seed", type=int, required=True)
    parser.add_argument("--or-seeds", default="101,211,307")
    parser.add_argument("--max-parallel", type=int, default=4)
    parser.add_argument("--orfs-cores", type=int, default=12)
    parser.add_argument("--search-domain", default="official_autotuner_independent_v2",
                        choices=("official_autotuner_independent_v2", "calibrated_full"))
    parser.add_argument("--expected-controller-source-sha256")
    parser.add_argument("--expected-python-environment-sha256")
    parser.add_argument(
        "--local-state-base", type=Path,
        default=Path(f"/var/tmp/openroad-platform-dse-{os.getuid()}"),
        help="Node-local root for live SQLite state; shared/FUSE filesystems are rejected",
    )
    args = parser.parse_args()
    if not 1 <= args.budget <= 600 or not 1 <= args.max_parallel <= 16:
        parser.error("budget must be 1..600 and max-parallel 1..16")
    seeds = [int(value) for value in args.or_seeds.split(",")]
    minimum_seed_count = 1 if args.ablation == "single_replica_error_control" else 2
    if (len(seeds) < minimum_seed_count or len(seeds) > 8
            or len(set(seeds)) != len(seeds)):
        parser.error(f"or-seeds requires {minimum_seed_count}..8 distinct integers")
    protocol = json.loads(args.protocol.expanduser().resolve().read_text(encoding="utf-8"))
    validate_industrial_dse_protocol(protocol)
    orfs_root = args.orfs_root.expanduser().resolve()
    lock_path = args.toolchain_lock.expanduser().resolve()
    evidence_path = orfs_root / "toolchain-evidence.json"
    toolchain_validation = None
    if args.mode == "paper" or evidence_path.is_file():
        try:
            toolchain_validation = validate_pinned_orfs_toolchain(
                orfs_root, lock_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            parser.error(f"pinned toolchain validation failed: {exc}")
    if args.mode == "paper" and toolchain_validation is None:
        parser.error("paper mode requires a validated pinned ORFS toolchain")
    if args.mode == "paper":
        registered_ablations = {item["ablation_id"] for item in protocol["ablations"]}
        if args.ablation != "none" and args.ablation not in registered_ablations:
            parser.error("ablation is outside the frozen protocol")
        if args.ablation != "none" and args.budget != protocol["ablation_budget"]:
            parser.error("paper ablations must use the frozen ablation budget")
        if args.ablation == "none" and args.budget not in protocol["budget_checkpoints"]:
            parser.error("paper budget is outside the frozen protocol checkpoints")
        if args.optimizer_seed not in protocol["optimizer_seeds"]:
            parser.error("optimizer seed is outside the frozen protocol")
        expected_seeds = (protocol["paired_or_seeds"][:1]
                          if args.ablation == "single_replica_error_control"
                          else protocol["paired_or_seeds"])
        if seeds != expected_seeds:
            parser.error("paper OR_SEED vector must exactly match the frozen protocol")
        required_ablation_arm = ("stateful_portfolio" if (
            (protocol.get("full_domain_arm") or {}).get("optimizer") ==
            "stateful-l2-portfolio-v1") else "portfolio")
        if args.ablation != "none" and (
                args.arm != required_ablation_arm or args.search_domain != "calibrated_full"):
            parser.error("paper ablations remove one component from the full-domain portfolio")
        common_arms = {row["arm_id"] for row in protocol["common_domain_arms"]}
        full_arms = {row["arm_id"] for row in protocol["full_domain_arms"]}
        protocol_arm = ({"portfolio": "industrial_portfolio",
                         "stateful_portfolio": "stateful_l2_portfolio"}
                        .get(args.arm, args.arm))
        if protocol_arm in full_arms:
            if args.search_domain != "calibrated_full":
                parser.error("full-domain paper arms require the calibrated full domain")
        elif args.arm not in common_arms or args.search_domain != "official_autotuner_independent_v2":
            parser.error("paper comparison arms require the frozen common domain")

    output = args.output.expanduser().resolve(); output.mkdir(parents=True, exist_ok=True)
    lock_stream = (output / "experiment.lock").open("a+")
    try:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("the experiment cell already has an active controller", file=sys.stderr)
        return 2
    reference = load_orfs_reference_design(
        orfs_root, platform=args.platform, design=args.design)
    source_snapshot = _controller_source_snapshot()
    if args.mode == "paper":
        frozen_source_digest = _frozen_controller_digest(protocol)
        if frozen_source_digest != source_snapshot["digest"]:
            parser.error(
                "controller source does not match the content hash frozen in the study protocol")
    if (args.expected_controller_source_sha256
            and source_snapshot["digest"] != args.expected_controller_source_sha256):
        parser.error("controller source changed after the campaign manifest was frozen")
    python_environment = combined_python_environment(
        controller=current_python_environment())
    if (args.expected_python_environment_sha256
            and python_environment["fingerprint"] !=
            args.expected_python_environment_sha256):
        parser.error("Python optimization environment changed after campaign freeze")
    cell_manifest = {
        "schema_version": 1, "kind": "industrial-dse-cell-binding",
        "platform": args.platform, "design": args.design, "arm": args.arm,
        "ablation": args.ablation,
        "budget": args.budget, "optimizer_seed": args.optimizer_seed,
        "paired_or_seeds": seeds, "search_domain": args.search_domain,
        "frozen_study_protocol_digest": protocol["protocol_digest"],
        "common_evaluator_schema": EVALUATOR_SCHEMA,
        "reference_design_fingerprint": reference.source_fingerprint,
        "reference_clock_period_ns": reference.clock_period_ns,
        "orfs_commit": reference.orfs_commit,
        "toolchain_validated": bool(toolchain_validation),
        "toolchain_validation_fingerprint": (
            toolchain_validation["validation_fingerprint"]
            if toolchain_validation else None),
        "toolchain_lock_sha256": (
            toolchain_validation["lock_sha256"] if toolchain_validation else None),
        "controller_source_snapshot_sha256": source_snapshot["digest"],
        "python_environment_fingerprint": python_environment["fingerprint"],
        "study_mode": args.mode,
    }
    try:
        _bind_output_to_cell(output, cell_manifest)
    except (ValueError, json.JSONDecodeError) as exc:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN); lock_stream.close()
        print(str(exc), file=sys.stderr)
        return 2
    cell_binding_sha256 = _digest(cell_manifest)
    local_state_root = args.local_state_base.expanduser().resolve() / cell_binding_sha256
    state_mirror = LocalStateMirror(
        local_root=local_state_root,
        shared_root=output,
        binding_sha256=cell_binding_sha256,
    )
    try:
        storage_state = state_mirror.prepare()
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN); lock_stream.close()
        print(f"local SQLite state preparation failed: {exc}", file=sys.stderr)
        return 2
    _atomic(output / "state-storage-policy.json", {
        **storage_state,
        "local_state_identity": cell_binding_sha256,
        "shared_artifact_root": str(output),
        "runtime_workspace_root": str(output / "runtime-workspaces"),
    })
    if args.mode == "preflight":
        _atomic(output / "EXCLUDED_FROM_FORMAL_STUDY.json", {
            "excluded": True,
            "reason": "preflight mode is engineering evidence, not a preregistered paper cell",
            "study_mode": args.mode,
            "protocol_digest": protocol["protocol_digest"],
        })
    _atomic(output / "controller-source-snapshot.json", source_snapshot)
    _atomic(output / "python-environment.json", python_environment)
    if toolchain_validation:
        _atomic(output / "toolchain-validation.json", toolchain_validation)
    os.environ["OPENROAD_PLATFORM_PARAMETER_CALIBRATION"] = str(
        args.calibration.expanduser().resolve())
    os.environ["OPENROAD_PLATFORM_REQUIRE_PARAMETER_CALIBRATION"] = "1"
    os.environ["OPENROAD_PLATFORM_ORFS_CORES"] = str(args.orfs_cores)
    state = ApiState(
        local_state_root / "platform.db", output / "uploads", orfs_root,
        design_root=output / "designs", legacy_root=output / "legacy",
        runtime_db_path=local_state_root / "runtime.db",
        optimization_db_path=local_state_root / "optimization.db",
        runtime_workspace_root=output / "runtime-workspaces",
        load_taiwei_plugin=False,
    )
    experiment_key = (f"paper-{args.platform}-{args.design}-{args.arm}-"
                      f"a{args.ablation}-o{args.optimizer_seed}-b{args.budget}-"
                      f"e{EVALUATOR_SCHEMA}")
    created = state.start_bayesian_closed_loop({
        "reference_design": args.design, "platform": args.platform,
        "experiment_key": experiment_key, "objective_profile": "balanced",
        "repetitions": len(seeds), "replica_or_seeds": seeds,
        "max_rounds": args.budget, "stall_window": 3,
        "minimum_relative_improvement": .005,
        "optimizer_seed": args.optimizer_seed,
        "optimizer_backend": ARMS[args.arm],
        "ablation_id": args.ablation,
        "search_domain": args.search_domain, "max_parallel": args.max_parallel,
        "stage_timeout_seconds": 7200, "flow_timeout_seconds": 14400,
    })
    pipeline_id = created["pipeline_id"]
    try:
        while True:
            result = state.run_bayesian_closed_loop_to_boundary(
                pipeline_id, {"max_transitions": 1})
            current = result["state"]
            _atomic(output / "checkpoint-export.json", result)
            _atomic(output / "heartbeat.json", {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "pipeline_id": pipeline_id, "status": current["status"],
                "round": current["round"], "history_count": len(current["history"]),
                "protocol_fingerprint": current["protocol_fingerprint"],
            })
            snapshot = state_mirror.snapshot()
            _atomic(output / "state-mirror-receipt.json", {
                "sequence": snapshot.sequence, "slot": snapshot.slot,
                "database_count": snapshot.database_count,
                "manifest": str(snapshot.manifest_path),
                "binding_sha256": cell_binding_sha256,
            })
            if current["status"] in TERMINAL:
                break
    finally:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN); lock_stream.close()
    print(json.dumps({
        "pipeline_id": pipeline_id, "status": current["status"],
        "round": current["round"], "best_feasible": current["best_feasible"],
        "best_utility": current["best_utility"],
        "ablation": args.ablation,
        "protocol_fingerprint": current["protocol_fingerprint"],
        "frozen_study_protocol_digest": protocol["protocol_digest"],
    }))
    return 0 if current["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
