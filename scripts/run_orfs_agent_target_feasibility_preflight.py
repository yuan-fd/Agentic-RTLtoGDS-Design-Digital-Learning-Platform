#!/usr/bin/env python3
"""Run a bounded AES feasibility preflight before an ORFS-Agent L2 campaign.

The preflight is deliberately separate from the formal GP/EI campaign.  It
does not invoke an optimizer and cannot report an improvement.  Its sole
output is an artifact-backed, subtractive domain derived from repeated,
one-factor perturbations around the frozen ORFS-Agent AES anchor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
for source in (
    ROOT, ROOT / "packages/contracts/src", ROOT / "packages/execution/src",
    ROOT / "packages/scheduler/src", ROOT / "packages/analysis/src",
):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from openroad_platform_analysis import ORFSProtectedEvaluator  # noqa: E402
from openroad_platform_analysis.target_feasibility import (  # noqa: E402
    aggregate_target_feasibility, build_anchor_perturbation_plan,
)
from openroad_platform_contracts import RuntimeStatus  # noqa: E402
from openroad_platform_execution import (  # noqa: E402
    PluginRegistry, ToolchainConfig, build_orfs_task, load_orfs_reference_design,
    orfs_plugin_manifest, validate_orfs_parameters, validate_pinned_orfs_toolchain,
)
from openroad_platform_scheduler import (  # noqa: E402
    LocalThreadExecutionBackend, RuntimeStore, WorkflowRuntime,
)


COMMON_EVALUATION = "orfs/implementation/analysis/common_evaluation.json"
TARGET = ("sky130hd", "aes")
# This exact current-toolchain baseline was independently measured three times
# by v3's protected evaluator at the same RTL/SDC/toolchain identity.  It is
# an anchor for a *new* preflight, not recycled QoR data. Clock period remains
# a frozen protected input, not an optimisation variable.
ANCHOR = {
    "core_utilization_pct": 20,
    "tns_end_percent": 100,
    "global_placement_padding": 0,
    "detail_placement_padding": 0,
    "enable_dpo": 1,
    "place_density_lb_addon": 0.4936,
    "cts_cluster_size": 20,
    "cts_cluster_diameter": 80,
    "gpl_timing_driven": 1,
    "gpl_routability_driven": 1,
    "routing_layer_adjustment": .5,
}
LEVELS = {
    "core_utilization_pct": [20, 30, 40],
    "tns_end_percent": [50, 75, 100],
    "global_placement_padding": [0, 1, 2, 3],
    # DP_PAD cannot be raised in a one-factor perturbation while the anchor
    # GP_PAD remains zero; it stays explicitly fixed in this first slice.
    "detail_placement_padding": [0],
    "enable_dpo": [0, 1],
    "place_density_lb_addon": [0.35, 0.425, 0.4936],
    "cts_cluster_size": [10, 20, 30],
    "cts_cluster_diameter": [80, 100, 120],
}
REPLICAS = (101, 211, 307)


def _atomic_json(path: Path, value: object) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True),
                         encoding="utf-8")
    temporary.replace(path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _freeze_sdc(*, output: Path, source: Path, period_ns: float) -> Path:
    """Materialize the 4.5 ns target exactly once outside the ORFS worktree."""
    destination = output / "frozen-inputs" / "constraint.sdc"
    destination.parent.mkdir(parents=True, exist_ok=True)
    text = source.read_text(encoding="utf-8")
    replaced, count = re.subn(
        r"(?m)^set\s+clk_period\s+[^\s#]+", f"set clk_period {period_ns:g}", text,
    )
    if count != 1:
        raise ValueError("reference SDC must contain exactly one clk_period declaration")
    if destination.exists() and destination.read_text(encoding="utf-8") != replaced:
        raise ValueError("preflight output is already bound to different frozen SDC bytes")
    if not destination.exists():
        destination.write_text(replaced, encoding="utf-8")
    return destination


def _canonical_evaluation(store: RuntimeStore, run_id: str) -> dict[str, Any] | None:
    description = store.describe_run(run_id)
    attempts = [attempt for stage in description["stages"] for attempt in stage["attempts"]]
    if len(attempts) != 1:
        return None
    artifact = next((item for item in attempts[0]["artifacts"]
                     if item["store_key"] == COMMON_EVALUATION), None)
    if artifact is None:
        return None
    path = Path(attempts[0]["workspace"]) / artifact["store_key"]
    if (not path.is_file() or path.stat().st_size != artifact["size_bytes"]
            or _sha256(path) != artifact["sha256"]):
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _outcome(store: RuntimeStore, run_id: str) -> dict[str, Any]:
    run = store.get_run(run_id)
    result: dict[str, Any] = {"run_id": run_id, "status": run.status.value}
    if run.status is RuntimeStatus.SUCCEEDED:
        evaluation = _canonical_evaluation(store, run_id)
        result["evaluator_feasible"] = bool(evaluation and evaluation.get("feasible"))
        result["evaluation_id"] = evaluation.get("evaluation_id") if evaluation else None
    else:
        attempts = [attempt for stage in store.describe_run(run_id)["stages"]
                    for attempt in stage["attempts"]]
        result["evaluator_feasible"] = False
        result["failure"] = attempts[-1].get("failure") if attempts else None
    return result


def _receipt(*, output: Path, toolchain: Mapping[str, Any], reference: Any,
             frozen_sdc: Path, cases: list[dict[str, Any]], max_parallel: int,
             cores_per_run: int, stage_timeout: int, flow_timeout: int) -> dict[str, Any]:
    value = {
        "schema_version": 1,
        "kind": "orfs-agent-target-feasibility-preflight",
        "status": "running",
        "claim_boundary": (
            "Target-design feasibility evidence only; this does not invoke GP/EI, "
            "does not compare QoR, and is not an upstream-paper number reproduction."
        ),
        "target": {"platform": TARGET[0], "design": TARGET[1], "top": reference.top,
                   "clock": reference.clock, "clock_period_ns": 4.5,
                   "source_fingerprint": reference.source_fingerprint,
                   "orfs_commit": reference.orfs_commit},
        "anchor": ANCHOR,
        "levels": LEVELS,
        "replicas": list(REPLICAS),
        "case_count": len(cases),
        "frozen_sdc": {"path": str(frozen_sdc), "sha256": _sha256(frozen_sdc)},
        "toolchain_validation_fingerprint": toolchain["validation_fingerprint"],
        "resource_policy": {
            "max_parallel": max_parallel,
            "orfs_cores_per_run": cores_per_run,
            "stage_timeout_seconds": stage_timeout,
            "flow_timeout_seconds": flow_timeout,
        },
    }
    value["receipt_digest"] = hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--orfs-root", type=Path, default=ROOT / "var/toolchains/orfs-51ad1231-clean")
    parser.add_argument("--toolchain-lock", type=Path,
                        default=ROOT / "integrations/orfs/orfs-industrial-v2.lock.json")
    parser.add_argument("--openroad-bin", type=Path, default=Path.home() / "bin/openroad")
    parser.add_argument("--yosys-bin", type=Path, default=Path.home() / "bin/yosys")
    parser.add_argument("--klayout-bin", type=Path, default=Path.home() / "bin/klayout")
    parser.add_argument("--max-parallel", type=int, default=8)
    parser.add_argument("--orfs-cores-per-run", type=int, default=4)
    parser.add_argument("--stage-timeout", type=int, default=3600)
    parser.add_argument("--flow-timeout", type=int, default=7200)
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.max_parallel <= 16 or not 1 <= args.orfs_cores_per_run <= 16:
        parser.error("max-parallel and orfs-cores-per-run must both be 1..16")
    if args.max_parallel * args.orfs_cores_per_run > (os.cpu_count() or 1):
        parser.error("max-parallel × orfs-cores-per-run exceeds visible CPU budget")
    if args.stage_timeout <= 0 or args.flow_timeout < args.stage_timeout:
        parser.error("flow-timeout must be at least stage-timeout, and both must be positive")

    output = args.output.expanduser().resolve()
    # A detached supervisor creates its stdout/stderr and PID receipts before
    # Python begins.  They are operational metadata, not prior experiment
    # evidence.  Any other pre-existing entry would risk mixing campaigns and
    # remains a hard error.
    permitted_supervisor_entries = {"controller.log", "controller.pid"}
    existing = (set(item.name for item in output.iterdir()) if output.exists() else set())
    if existing - permitted_supervisor_entries:
        raise ValueError("preflight output must be new apart from controller.log/controller.pid")
    output.mkdir(parents=True, exist_ok=True)
    orfs_root = args.orfs_root.expanduser().resolve()
    validation = validate_pinned_orfs_toolchain(orfs_root, args.toolchain_lock)
    reference = load_orfs_reference_design(orfs_root, platform=TARGET[0], design=TARGET[1])
    frozen_sdc = _freeze_sdc(output=output, source=reference.sdc_path, period_ns=4.5)
    cases = build_anchor_perturbation_plan(anchor=ANCHOR, levels=LEVELS, seeds=REPLICAS)
    # Validate the whole frozen plan before writing a single Runtime run.  A
    # plan/contract mismatch is an admission failure, not an EDA observation.
    for case in cases:
        validate_orfs_parameters(case["parameters"], platform=TARGET[0])
    receipt = _receipt(output=output, toolchain=validation, reference=reference,
                       frozen_sdc=frozen_sdc, cases=cases, max_parallel=args.max_parallel,
                       cores_per_run=args.orfs_cores_per_run,
                       stage_timeout=args.stage_timeout, flow_timeout=args.flow_timeout)
    _atomic_json(output / "preflight-receipt.json", receipt)
    _atomic_json(output / "preflight-plan.json", {"receipt_digest": receipt["receipt_digest"],
                                                    "cases": cases})
    if args.plan_only:
        print(json.dumps({"output": str(output), "case_count": len(cases),
                          "receipt_digest": receipt["receipt_digest"]}, indent=2))
        return 0

    os.environ["OPENROAD_PLATFORM_ORFS_CORES"] = str(args.orfs_cores_per_run)
    toolchain = ToolchainConfig(
        name="orfs-agent-target-feasibility-preflight", orfs_root=orfs_root,
        openroad_bin=args.openroad_bin.expanduser().resolve(),
        yosys_bin=args.yosys_bin.expanduser().resolve(),
        klayout_bin=args.klayout_bin.expanduser().resolve(),
    )
    toolchain.validate()
    runtime_store = RuntimeStore(output / "runtime.db")
    runtime = WorkflowRuntime(
        runtime_store, PluginRegistry([orfs_plugin_manifest(toolchain, default_timeout_seconds=args.flow_timeout)]),
        workspace_root=output / "attempts", worker_id="orfs-agent-target-feasibility",
        lease_seconds=180, protected_evaluator=ORFSProtectedEvaluator(),
    )
    main_rtl = next(path for path in reference.rtl_files if path.stem == reference.top)
    run_ids = {}
    for case in cases:
        parameters = validate_orfs_parameters(case["parameters"], platform=TARGET[0])
        task = build_orfs_task(
            main_rtl, project_id="orfs-agent-target-feasibility", design_id=TARGET[1],
            top=reference.top, clock=reference.clock, platform_name=TARGET[0],
            target_stage="finish", clock_period_ns=4.5,
            core_utilization_pct=float(parameters["core_utilization_pct"]),
            place_density=float(reference.native_baseline_overrides.get("place_density", .55)),
            or_seed=int(case["or_seed"]), stage_timeout_seconds=args.stage_timeout,
            timeout_seconds=args.flow_timeout, flow_parameters=parameters,
            rtl_files=reference.rtl_files, rtl_root=reference.rtl_root,
            rtl_include_dirs=reference.include_dirs,
            synth_hdl_frontend=reference.synth_hdl_frontend,
            design_options=dict(reference.design_options), sdc_path=frozen_sdc,
            task_id=f"orfs-agent-feasibility-{case['case_id']}",
            labels={"preflight": "orfs-agent-target-feasibility",
                    "case_id": case["case_id"],
                    "design_bundle_sha256": reference.source_fingerprint},
        )
        run_ids[case["case_id"]] = runtime.submit(task).run_id
    backend = LocalThreadExecutionBackend()
    backend_receipt = backend.run_bound(runtime, list(run_ids.values()), max_parallel=args.max_parallel)
    outcomes = {case_id: _outcome(runtime_store, run_id) for case_id, run_id in run_ids.items()}
    report = aggregate_target_feasibility(
        anchor=ANCHOR, cases=cases, outcomes=outcomes, required_seeds=REPLICAS,
    )
    _atomic_json(output / "runtime-execution-receipt.json", backend_receipt)
    _atomic_json(output / "outcomes.json", outcomes)
    _atomic_json(output / "target-feasibility-report.json", report)
    _atomic_json(output / "preflight-receipt.json", {**receipt, "status": "completed",
                                                        "report_sha256": _sha256(output / "target-feasibility-report.json")})
    print(json.dumps({"output": str(output), "case_count": len(cases),
                      "dimension_count": len(report["dimensions"]),
                      "fixed_parameter_count": len(report["fixed_parameters"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
