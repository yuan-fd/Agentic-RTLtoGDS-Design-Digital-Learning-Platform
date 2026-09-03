#!/usr/bin/env python3
"""Launch/resume the preregistered official AutoTuner comparison matrix."""

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
    external_python_environment,
)


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/run_official_autotuner_baseline.py"


def _controller_source_snapshot() -> dict:
    """Freeze every Python module that can affect proposal evaluation."""
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
    for source_root in roots:
        files.extend(sorted(source_root.rglob("*.py")))
    records = [{
        "path": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    } for path in sorted(set(files))]
    return {"digest": _digest(records), "file_count": len(records), "files": records}


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


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def build_cells(protocol: dict, *, blocks: list[str], seeds: list[int],
                budget: int, mode: str) -> list[dict]:
    rows = []
    for block in protocol["primary_blocks"]:
        key = f"{block['platform']}/{block['design']}"
        if blocks and key not in blocks:
            continue
        for seed in seeds:
            rows.append({
                "cell_id": (f"{block['platform']}-{block['design']}-"
                            f"official-hyperopt-o{seed}-b{budget}"),
                "platform": block["platform"], "design": block["design"],
                "optimizer_seed": seed, "budget": budget, "mode": mode,
            })
    return rows


def _run_cell(cell: dict, *, root: Path, protocol: Path, calibration: Path,
              orfs_root: Path, toolchain_lock: Path, autotuner_root: Path,
              python: Path, jobs: int, openroad_threads: int,
              timeout_hours: float, runner_sha256: str,
              controller_source_sha256: str,
              python_environment_sha256: str) -> dict:
    output = root / "cells" / cell["cell_id"]
    output.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, str(RUNNER), "--output", str(output),
        "--protocol", str(protocol), "--mode", cell["mode"],
        "--calibration", str(calibration), "--orfs-root", str(orfs_root),
        "--toolchain-lock", str(toolchain_lock),
        "--expected-runner-sha256", runner_sha256,
        "--expected-controller-source-sha256", controller_source_sha256,
        "--expected-python-environment-sha256", python_environment_sha256,
        "--autotuner-root", str(autotuner_root), "--python", str(python),
        "--platform", cell["platform"], "--reference-design", cell["design"],
        "--algorithm", "hyperopt", "--samples", str(cell["budget"]),
        "--optimizer-seed", str(cell["optimizer_seed"]),
        "--or-seed", "101", "--paired-or-seeds", "101,211,307",
        "--jobs", str(jobs), "--openroad-threads", str(openroad_threads),
        "--stop-stage", "finish", "--timeout-hours", str(timeout_hours),
    ]
    started = _now()
    log_path = output / "campaign-controller.log"
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n[{started}] command={json.dumps(command)}\n"); log.flush()
        completed = subprocess.run(
            command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=False)
    result_path = output / "result.json"
    result_status = None
    if result_path.is_file():
        try:
            result_status = json.loads(
                result_path.read_text(encoding="utf-8")).get("status")
        except json.JSONDecodeError:
            result_status = "invalid_result"
    return {
        **cell, "started_at": started, "ended_at": _now(),
        "exit_code": completed.returncode, "terminal_status": result_status,
        "output": str(output), "log": str(log_path),
        "log_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=
                        ROOT / "studies/protocols/v2-industrial-dse-20260829-r27.protocol.json")
    parser.add_argument("--calibration", type=Path, default=
                        ROOT / "var/calibration/orfs-parameters-v2/parameter_calibration_report.json")
    parser.add_argument("--orfs-root", type=Path,
                        default=ROOT / "var/toolchains/orfs-51ad1231-clean")
    parser.add_argument("--toolchain-lock", type=Path, default=
                        ROOT / "integrations/orfs/orfs-industrial-v2.lock.json")
    parser.add_argument("--autotuner-root", type=Path,
                        help="Defaults to tools/AutoTuner inside the pinned ORFS worktree")
    parser.add_argument("--python", type=Path,
                        default=ROOT / ".tools/venvs/orfs-autotuner/bin/python")
    parser.add_argument("--mode", choices=("preflight", "paper"), default="paper")
    parser.add_argument("--blocks", default="")
    parser.add_argument("--optimizer-seeds", default="1103,2207,3301")
    parser.add_argument("--budget", type=int, default=600)
    parser.add_argument("--max-concurrent-cells", type=int, default=1)
    parser.add_argument("--jobs-per-cell", type=int, default=4)
    parser.add_argument("--openroad-threads", type=int, default=12)
    parser.add_argument("--max-total-orfs-workers", type=int, default=4)
    parser.add_argument("--max-cpu-fraction", type=float, default=.80)
    parser.add_argument("--timeout-hours", type=float, default=4.0)
    args = parser.parse_args()

    protocol_path = args.protocol.expanduser().resolve()
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    resolved_orfs_root = args.orfs_root.expanduser().resolve()
    resolved_autotuner_root = (args.autotuner_root.expanduser().resolve()
                               if args.autotuner_root else
                               resolved_orfs_root / "tools/AutoTuner")
    blocks = _csv(args.blocks)
    valid_blocks = {f"{item['platform']}/{item['design']}"
                    for item in protocol["primary_blocks"]}
    if any(item not in valid_blocks for item in blocks):
        parser.error("blocks must come from the frozen primary matrix")
    seeds = [int(item) for item in _csv(args.optimizer_seeds)]
    if args.mode == "paper" and (
            seeds != protocol["optimizer_seeds"]
            or args.budget != max(protocol["budget_checkpoints"])):
        parser.error("paper seed vector and budget must match the frozen protocol")
    if min(args.max_concurrent_cells, args.jobs_per_cell,
           args.openroad_threads, args.max_total_orfs_workers) < 1:
        parser.error("resource limits must be positive")
    workers = args.max_concurrent_cells * args.jobs_per_cell
    if workers > args.max_total_orfs_workers:
        parser.error("concurrent cells exceed the global ORFS worker limit")
    cpu_cap = max(1, int((os.cpu_count() or 1) * args.max_cpu_fraction))
    planned_threads = workers * args.openroad_threads
    if not .1 <= args.max_cpu_fraction <= .9 or planned_threads > cpu_cap:
        parser.error("planned official AutoTuner threads exceed the CPU policy")

    output = args.output.expanduser().resolve(); output.mkdir(parents=True, exist_ok=True)
    lock = (output / "campaign.lock").open("a+")
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("official campaign already has an active launcher", file=sys.stderr)
        return 2
    cells = build_cells(
        protocol, blocks=blocks, seeds=seeds, budget=args.budget, mode=args.mode)
    runner_sha256 = hashlib.sha256(
        (ROOT / "scripts/run_official_autotuner_baseline.py").read_bytes()).hexdigest()
    controller_source_snapshot = _controller_source_snapshot()
    python_environment = combined_python_environment(
        controller=current_python_environment(),
        external=external_python_environment(args.python),
    )
    manifest = {
        "schema_version": 1, "kind": "official-autotuner-campaign",
        "protocol_digest": protocol["protocol_digest"],
        "protocol_path": str(protocol_path), "mode": args.mode,
        "blocks": blocks or sorted(valid_blocks), "seeds": seeds,
        "budget": args.budget, "cells": cells,
        "runner_sha256": runner_sha256,
        "controller_source_snapshot_sha256": controller_source_snapshot["digest"],
        "python_environment_fingerprint": python_environment["fingerprint"],
        "resource_policy": {
            "max_concurrent_cells": args.max_concurrent_cells,
            "jobs_per_cell": args.jobs_per_cell,
            "openroad_threads": args.openroad_threads,
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
            print("official campaign output is bound to another manifest", file=sys.stderr)
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
               not in {"succeeded", "failed"}]
    try:
        with ThreadPoolExecutor(max_workers=args.max_concurrent_cells) as pool:
            futures = {pool.submit(
                _run_cell, cell, root=output, protocol=protocol_path,
                calibration=args.calibration.expanduser().resolve(),
                orfs_root=resolved_orfs_root,
                toolchain_lock=args.toolchain_lock.expanduser().resolve(),
                autotuner_root=resolved_autotuner_root,
                python=args.python.expanduser().absolute(), jobs=args.jobs_per_cell,
                openroad_threads=args.openroad_threads,
                timeout_hours=args.timeout_hours,
                runner_sha256=runner_sha256,
                controller_source_sha256=controller_source_snapshot["digest"],
                python_environment_sha256=python_environment["fingerprint"]):
                cell for cell in pending}
            for future in as_completed(futures):
                row = future.result(); progress[row["cell_id"]] = row
                _atomic(progress_path, progress)
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN); lock.close()
    rows = [progress.get(cell["cell_id"], {**cell, "terminal_status": "not_run"})
            for cell in cells]
    report = {
        "schema_version": 1, "kind": "official-autotuner-campaign-result",
        "campaign_fingerprint": manifest["campaign_fingerprint"], "cells": rows,
        "counts": {status: sum(row.get("terminal_status") == status for row in rows)
                   for status in ("succeeded", "failed", "not_run")},
        "claim_boundary": (
            "Execution ledger only; comparison requires evidence aggregation and "
            "paired statistics with native optimizer cells."),
    }
    _atomic(output / "campaign-report.json", report)
    print(json.dumps(report["counts"]))
    return 0 if all(row.get("terminal_status") == "succeeded" for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
