#!/usr/bin/env python3
"""Launch/resume a resource-bounded matrix of durable industrial DSE cells."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

for source in sorted((Path(__file__).resolve().parents[1] / "packages").glob("*/src")):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from openroad_platform_analysis.environment_snapshot import (  # noqa: E402
    combined_python_environment, current_python_environment,
)


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/run_industrial_dse_experiment.py"
NATIVE_ARMS = (
    "random", "sobol", "tpe", "qlognehvi",
    "random_full", "sobol_full", "portfolio", "stateful_portfolio",
)


def _controller_source_snapshot() -> dict:
    roots = (
        ROOT / "apps/api", ROOT / "packages/analysis/src",
        ROOT / "packages/contracts/src", ROOT / "packages/execution/src",
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
    return {"digest": _digest(records), "file_count": len(records), "files": records}


def _frozen_controller_digest(protocol: dict) -> str | None:
    snapshot = ((protocol.get("reproducibility") or {}).get("source_snapshot")
                or {})
    controller = snapshot.get("controller") if isinstance(snapshot, dict) else None
    digest = controller.get("digest") if isinstance(controller, dict) else None
    return str(digest) if isinstance(digest, str) and digest else None
ABLATIONS = (
    "none", "no_gp", "no_multifidelity", "no_feasibility",
    "no_trust_region", "no_memory", "no_stage_focus", "no_edair",
    "no_safe_initialization", "no_state_policy",
    "single_replica_error_control",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _cell_id(block: dict, arm: str, seed: int, budget: int, ablation: str) -> str:
    suffix = "" if ablation == "none" else f"-a{ablation}"
    return f"{block['platform']}-{block['design']}-{arm}{suffix}-o{seed}-b{budget}"


def build_cells(protocol: dict, *, arms: list[str], seeds: list[int],
                blocks: list[str], budget: int, mode: str,
                ablations: list[str] | None = None) -> list[dict]:
    ablations = ablations or ["none"]
    full_arm = ("stateful_portfolio" if (
        (protocol.get("full_domain_arm") or {}).get("optimizer") ==
        "stateful-l2-portfolio-v1") else "portfolio")
    selected = []
    for block in protocol["primary_blocks"]:
        key = f"{block['platform']}/{block['design']}"
        if blocks and key not in blocks:
            continue
        for ablation in ablations:
            ablation_arms = [full_arm] if ablation != "none" else arms
            for arm in ablation_arms:
                domain = ("calibrated_full" if arm in {
                              "random_full", "sobol_full", "portfolio",
                              "stateful_portfolio"}
                          else "official_autotuner_independent_v2")
                for seed in seeds:
                    selected.append({
                        "cell_id": _cell_id(block, arm, seed, budget, ablation),
                        "platform": block["platform"], "design": block["design"],
                        "arm": arm, "ablation": ablation,
                        "optimizer_seed": seed, "budget": budget,
                        "mode": mode, "search_domain": domain,
                    })
    return selected


def _run_cell(cell: dict, *, root: Path, protocol: Path, calibration: Path,
              orfs_root: Path, toolchain_lock: Path,
              controller_source_sha256: str,
              python_environment_sha256: str,
              max_parallel: int, orfs_cores: int) -> dict:
    output = root / "cells" / cell["cell_id"]
    # The experiment runner owns its output directory and rejects an unbound
    # non-empty directory.  Campaign diagnostics therefore live outside that
    # namespace; otherwise merely opening a controller log prevents the runner
    # from creating its required cell manifest.
    log_path = root / "controller-logs" / f"{cell['cell_id']}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, str(RUNNER), "--output", str(output),
        "--orfs-root", str(orfs_root), "--calibration", str(calibration),
        "--toolchain-lock", str(toolchain_lock),
        "--expected-controller-source-sha256", controller_source_sha256,
        "--expected-python-environment-sha256", python_environment_sha256,
        "--protocol", str(protocol), "--mode", cell["mode"],
        "--platform", cell["platform"], "--design", cell["design"],
        "--arm", cell["arm"], "--budget", str(cell["budget"]),
        "--ablation", cell.get("ablation", "none"),
        "--optimizer-seed", str(cell["optimizer_seed"]),
        "--or-seeds", ("101" if cell.get("ablation") ==
                       "single_replica_error_control" else "101,211,307"),
        "--max-parallel", str(max_parallel),
        "--orfs-cores", str(orfs_cores), "--search-domain", cell["search_domain"],
    ]
    started = _now()
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n[{started}] command={json.dumps(command)}\n")
        log.flush()
        completed = subprocess.run(
            command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=False)
    ended = _now()
    checkpoint = output / "checkpoint-export.json"
    terminal = None
    if checkpoint.is_file():
        try:
            terminal = json.loads(checkpoint.read_text(encoding="utf-8"))["state"]["status"]
        except (KeyError, json.JSONDecodeError):
            terminal = "invalid_checkpoint"
    return {
        **cell, "started_at": started, "ended_at": ended,
        "exit_code": completed.returncode, "terminal_status": terminal,
        "output": str(output), "log": str(log_path),
        "log_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=
                        ROOT / "studies/protocols/v2-industrial-dse-20260830-r31-stateful-l2.protocol.json")
    parser.add_argument("--calibration", type=Path, default=
                        ROOT / "var/calibration/orfs-parameters-v2/parameter_calibration_report.json")
    parser.add_argument("--orfs-root", type=Path,
                        default=ROOT / "var/toolchains/orfs-51ad1231-clean")
    parser.add_argument("--toolchain-lock", type=Path, default=
                        ROOT / "integrations/orfs/orfs-industrial-v2.lock.json")
    parser.add_argument("--mode", choices=("preflight", "paper"), default="paper")
    parser.add_argument("--arms", default=(
        "random,sobol,tpe,qlognehvi,random_full,sobol_full,stateful_portfolio"))
    parser.add_argument("--ablations", default="none")
    parser.add_argument("--blocks", default="")
    parser.add_argument("--optimizer-seeds", default="1103,2207,3301")
    parser.add_argument("--budget", type=int, default=600)
    parser.add_argument("--max-concurrent-cells", type=int, default=1)
    parser.add_argument("--max-parallel-per-cell", type=int, default=4)
    parser.add_argument("--orfs-cores", type=int, default=12)
    parser.add_argument("--max-total-orfs-workers", type=int, default=4)
    parser.add_argument("--max-cpu-fraction", type=float, default=.80)
    args = parser.parse_args()

    protocol_path = args.protocol.expanduser().resolve()
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    arms = _parse_csv(args.arms)
    if not arms or any(arm not in NATIVE_ARMS for arm in arms):
        parser.error(f"arms must be drawn from {','.join(NATIVE_ARMS)}")
    ablations = _parse_csv(args.ablations)
    if not ablations or any(item not in ABLATIONS for item in ablations):
        parser.error(f"ablations must be drawn from {','.join(ABLATIONS)}")
    if "none" in ablations and len(ablations) > 1:
        parser.error("run primary arms and ablations in separate campaign roots")
    blocks = _parse_csv(args.blocks)
    valid_blocks = {f"{item['platform']}/{item['design']}"
                    for item in protocol["primary_blocks"]}
    if any(item not in valid_blocks for item in blocks):
        parser.error("blocks must use platform/design entries from the frozen protocol")
    seeds = [int(item) for item in _parse_csv(args.optimizer_seeds)]
    if args.mode == "paper":
        if seeds != protocol["optimizer_seeds"]:
            parser.error("paper campaign must use the complete ordered optimizer seed vector")
        expected_budget = (protocol["ablation_budget"] if ablations != ["none"]
                           else max(protocol["budget_checkpoints"]))
        if args.budget != expected_budget:
            parser.error("paper campaign budget does not match the frozen protocol")
    if min(args.max_concurrent_cells, args.max_parallel_per_cell,
           args.orfs_cores, args.max_total_orfs_workers) < 1:
        parser.error("resource limits must be positive")
    if not .1 <= args.max_cpu_fraction <= .9:
        parser.error("max-cpu-fraction must be between 0.1 and 0.9")
    if args.max_concurrent_cells * args.max_parallel_per_cell > args.max_total_orfs_workers:
        parser.error("concurrent cells exceed the global ORFS worker limit")
    planned_threads = (args.max_concurrent_cells * args.max_parallel_per_cell
                       * args.orfs_cores)
    cpu_cap = max(1, int((os.cpu_count() or 1) * args.max_cpu_fraction))
    if planned_threads > cpu_cap:
        parser.error(
            f"planned OpenROAD threads ({planned_threads}) exceed CPU cap ({cpu_cap})")

    output = args.output.expanduser().resolve(); output.mkdir(parents=True, exist_ok=True)
    lock = (output / "campaign.lock").open("a+")
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("campaign already has an active launcher", file=sys.stderr); return 2
    cells = build_cells(
        protocol, arms=arms, seeds=seeds, blocks=blocks,
        budget=args.budget, mode=args.mode, ablations=ablations)
    controller_source_snapshot = _controller_source_snapshot()
    if (args.mode == "paper"
            and _frozen_controller_digest(protocol) != controller_source_snapshot["digest"]):
        parser.error(
            "controller source does not match the content hash frozen in the study protocol")
    python_environment = combined_python_environment(
        controller=current_python_environment())
    manifest = {
        "schema_version": 1, "kind": "industrial-dse-campaign",
        "protocol_digest": protocol["protocol_digest"],
        "protocol_path": str(protocol_path), "mode": args.mode,
        "arms": arms, "ablations": ablations,
        "blocks": blocks or sorted(valid_blocks), "seeds": seeds,
        "budget": args.budget, "cells": cells,
        "controller_source_snapshot_sha256": controller_source_snapshot["digest"],
        "python_environment_fingerprint": python_environment["fingerprint"],
        "resource_policy": {
            "max_concurrent_cells": args.max_concurrent_cells,
            "max_parallel_per_cell": args.max_parallel_per_cell,
            "orfs_cores": args.orfs_cores,
            "max_total_orfs_workers": args.max_total_orfs_workers,
            "max_cpu_fraction": args.max_cpu_fraction,
            "logical_cpu_count": os.cpu_count(),
            "planned_openroad_threads": planned_threads,
            "openroad_thread_cap": cpu_cap,
        },
    }
    manifest["campaign_fingerprint"] = _digest(manifest)
    manifest_path = output / "campaign-manifest.json"
    if manifest_path.exists():
        if json.loads(manifest_path.read_text(encoding="utf-8")) != manifest:
            print("campaign output is bound to a different manifest", file=sys.stderr)
            return 2
    else:
        _atomic(manifest_path, manifest)
        _atomic(output / "controller-source-snapshot.json", controller_source_snapshot)
        _atomic(output / "python-environment.json", python_environment)
    progress_path = output / "campaign-progress.json"
    progress = (json.loads(progress_path.read_text(encoding="utf-8"))
                if progress_path.exists() else {})
    pending = [cell for cell in cells
               if progress.get(cell["cell_id"], {}).get("terminal_status")
               not in {"completed", "diagnosis_required", "failed"}]
    try:
        with ThreadPoolExecutor(max_workers=args.max_concurrent_cells) as pool:
            futures = {pool.submit(
                _run_cell, cell, root=output, protocol=protocol_path,
                calibration=args.calibration.expanduser().resolve(),
                orfs_root=args.orfs_root.expanduser().resolve(),
                toolchain_lock=args.toolchain_lock.expanduser().resolve(),
                controller_source_sha256=controller_source_snapshot["digest"],
                python_environment_sha256=python_environment["fingerprint"],
                max_parallel=args.max_parallel_per_cell,
                orfs_cores=args.orfs_cores): cell for cell in pending}
            for future in as_completed(futures):
                row = future.result()
                progress[row["cell_id"]] = row
                _atomic(progress_path, progress)
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN); lock.close()
    rows = [progress.get(cell["cell_id"], {**cell, "terminal_status": "not_run"})
            for cell in cells]
    report = {
        "schema_version": 1, "kind": "industrial-dse-campaign-result",
        "campaign_fingerprint": manifest["campaign_fingerprint"], "cells": rows,
        "counts": {status: sum(row.get("terminal_status") == status for row in rows)
                   for status in ("completed", "diagnosis_required", "failed", "not_run")},
        "claim_boundary": "Execution ledger only; optimizer claims require common-evaluator aggregation and paired statistics.",
    }
    _atomic(output / "campaign-report.json", report)
    print(json.dumps(report["counts"]))
    return 0 if all(row.get("terminal_status") in {
        "completed", "diagnosis_required"} for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
