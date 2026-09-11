#!/usr/bin/env python3
"""Run resumable, controlled ORFS parameter-liveness calibration."""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for rel in ("packages/contracts/src", "packages/execution/src", "packages/analysis/src"):
    sys.path.insert(0, str(ROOT / rel))

from openroad_platform_analysis.parameter_calibration import aggregate_parameter_calibration
from openroad_platform_contracts import RunRequest, RunStage
from openroad_platform_execution import ORFSRunner
from openroad_platform_execution.orfs_parameters import orfs_optimization_profile


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _anchors(spec: dict, baseline: object) -> list[object]:
    if spec["kind"] == "bool":
        return list(spec["choices"])
    del baseline
    midpoint = (spec["lower"] + spec["upper"]) / 2
    step = spec.get("step")
    if step:
        midpoint = spec["lower"] + round((midpoint - spec["lower"]) / step) * step
    if spec["kind"] == "int":
        midpoint = int(midpoint)
    values = [spec["lower"], midpoint, spec["upper"]]
    return list(dict.fromkeys(values))


def build_cases(*, output: Path, platforms: list[str], seeds: list[int],
                rtl: Path) -> list[dict]:
    cases = []
    for platform in platforms:
        profile = orfs_optimization_profile(platform)
        by_name = {item["name"]: item for item in profile["parameter_space"]}
        for spec in profile["parameter_space"]:
            parameter = spec["name"]
            for value in _anchors(spec, profile["baseline"][parameter]):
                controls = dict(profile["baseline"])
                # Padding changes the placer's minimum feasible density.  A
                # simultaneous positive LB addon can push the computed target
                # above 1.0 (observed reproducibly on Nangate45).  Hold addon
                # at zero in both padding sub-studies so the target knob is
                # isolated instead of measuring that known interaction.
                if parameter in {"global_placement_padding", "detail_placement_padding"}:
                    controls["place_density_lb_addon"] = 0.0
                    controls["core_utilization_pct"] = by_name["core_utilization_pct"]["lower"]
                # CTS parameters are consumed after placement.  The product
                # baseline is not necessarily a feasible calibration control:
                # ASAP7 GCD at 65% utilization plus a 0.20 density addon
                # reproducibly failed detailed placement for every cluster
                # value and paired seed.  Hold a conservative pre-CTS state
                # fixed so this experiment measures the target knob.
                if parameter in {"cts_cluster_size", "cts_cluster_diameter"}:
                    controls["place_density_lb_addon"] = 0.0
                    controls["core_utilization_pct"] = by_name["core_utilization_pct"]["lower"]
                # Detail padding is constrained by global padding.  Hold the
                # parent at its maximum for every level in this sub-study so
                # the target remains the only varying factor.
                if parameter == "detail_placement_padding":
                    controls["global_placement_padding"] = spec["upper"]
                controls[parameter] = value
                for seed in seeds:
                    value_slug = str(value).replace(".", "p")
                    identity = hashlib.sha256(json.dumps({
                        "platform": platform, "parameter": parameter,
                        "value": value, "controls": controls,
                        "target_stage": spec["stage"], "seed": seed,
                    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:10]
                    run_id = f"live-{platform}-{parameter}-{value_slug}-s{seed}-{identity}"
                    cases.append({
                        "case_id": run_id,
                        "platform": platform,
                        "design": "gcd",
                        "parameter": parameter,
                        "requested_value": value,
                        "control_parameters": controls,
                        "target_stage": spec["stage"],
                        "or_seed": seed,
                        "conditioning": {
                            "core_utilization_pct": controls["core_utilization_pct"],
                            "place_density_lb_addon": controls["place_density_lb_addon"],
                        } if parameter in {
                            "global_placement_padding", "detail_placement_padding",
                            "cts_cluster_size", "cts_cluster_diameter",
                        }
                        else {},
                        "rtl_path": str(rtl),
                        "workdir": str((output / "runs" / run_id).resolve()),
                    })
    return cases


def _run_case(case: dict, *, orfs_root: Path, work_root: Path,
              timeout: int) -> dict:
    workdir = Path(case["workdir"])
    result_path = workdir / "run_result.json"
    liveness_path = workdir / "analysis/parameter_liveness.json"
    if result_path.is_file() and liveness_path.is_file():
        return {"case_id": case["case_id"], "status": "resumed"}
    try:
        runner = ORFSRunner(orfs_root=orfs_root, work_root=work_root)
        request = RunRequest(
            rtl_path=case["rtl_path"], top="gcd", clock="clk",
            clock_period_ns=10.0, platform=case["platform"],
            target_stage=RunStage(case["target_stage"]),
            core_utilization_pct=float(case["control_parameters"]["core_utilization_pct"]),
            place_density=.45, flow_parameters=case["control_parameters"],
            or_seed=case["or_seed"], stage_timeout_seconds=timeout,
            run_id=case["case_id"], labels={"purpose": "parameter-liveness-calibration"},
        )
        result = runner.run(runner.prepare(request))
        return {"case_id": case["case_id"], "status": result.status.value,
                "seconds": sum(stage.seconds for stage in result.stages)}
    except Exception as exc:
        workdir.mkdir(parents=True, exist_ok=True)
        (workdir / "controller_error.log").write_text(
            f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}", encoding="utf-8")
        return {"case_id": case["case_id"], "status": "controller_error",
                "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(ROOT / "var/calibration/orfs-parameters-v1"))
    parser.add_argument("--orfs-root", default=str(Path.home() / "OpenROAD-flow-scripts"))
    parser.add_argument("--platforms", nargs="+", default=["nangate45", "asap7", "sky130hd"])
    parser.add_argument("--seeds", nargs="+", type=int, default=[101, 211, 307])
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--cores-per-run", type=int, default=6)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.workers <= 16 or not 1 <= args.cores_per_run <= 16:
        parser.error("workers and cores-per-run must each be between 1 and 16")
    output = Path(args.output).expanduser().resolve()
    orfs_root = Path(args.orfs_root).expanduser().resolve()
    rtl = orfs_root / "flow/designs/src/gcd/gcd.v"
    cases = build_cases(output=output, platforms=args.platforms, seeds=args.seeds, rtl=rtl)
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "protocol": "single-knob-low-mid-high-three-paired-seeds-v1",
        "orfs_root": str(orfs_root), "platforms": args.platforms,
        "seeds": args.seeds, "workers": args.workers,
        "cores_per_run": args.cores_per_run, "case_count": len(cases),
        "cases": cases,
        "claim_boundary": "Parameter transport/liveness calibration, not optimizer QoR evidence.",
    }
    _atomic_json(output / "calibration_plan.json", manifest)
    if args.plan_only:
        print(json.dumps({"plan": str(output / "calibration_plan.json"),
                          "case_count": len(cases)}, indent=2))
        return 0
    os.environ["OPENROAD_PLATFORM_ORFS_CORES"] = str(args.cores_per_run)
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_run_case, case, orfs_root=orfs_root,
                               work_root=output / "runs", timeout=args.timeout): case
                   for case in cases}
        for index, future in enumerate(as_completed(futures), 1):
            row = future.result()
            results.append(row)
            _atomic_json(output / "controller_checkpoint.json", {
                "schema_version": 1, "completed": index, "total": len(cases),
                "results": results,
            })
            print(f"[{index}/{len(cases)}] {row['case_id']}: {row['status']}", flush=True)
    report = aggregate_parameter_calibration(cases)
    _atomic_json(output / "parameter_calibration_report.json", report)
    print(json.dumps({"report": str(output / "parameter_calibration_report.json"),
                      "excluded": len(report["excluded_from_search"])}, indent=2))
    return 0 if not any(row["status"] == "controller_error" for row in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
