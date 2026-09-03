#!/usr/bin/env python3
"""Run one full-scale, evidence-preserving ORFS-Agent L2 campaign.

This runner is intentionally narrower than the web/API composition path.  It
binds an approved ORFS reference bundle, pinned toolchain, pinned ORFS-Agent
source and the frozen ``paper_comparable_external_l2_v1`` protocol into one
resumable evidence directory.  It does not contain a search algorithm: the
only numeric proposer is the admitted upstream GP/EI workbench.

The campaign shape follows the upstream project's public defaults: 50 diverse
initial configurations plus five 50-candidate GP/EI batches.  It is not an
"exact paper reproduction" unless the separate ORFS revision, benchmark and
objective identity checks also match the paper's stated environment.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
for source_root in (
    ROOT, ROOT / "packages/contracts/src", ROOT / "packages/execution/src",
    ROOT / "packages/scheduler/src", ROOT / "packages/analysis/src",
    ROOT / "packages/visualization/src",
):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from openroad_platform_analysis import ORFSProtectedEvaluator, RuntimeEvidenceExporter  # noqa: E402
from openroad_platform_analysis.target_feasibility import derive_target_execution_envelope  # noqa: E402
from openroad_platform_contracts import LearningContext, RuntimeStatus, TaskSpec  # noqa: E402
from openroad_platform_execution import (  # noqa: E402
    PluginRegistry, ToolchainConfig, build_orfs_agent_initial_warmup_recipes,
    build_orfs_agent_native_task, build_orfs_task, load_orfs_reference_design,
    orfs_agent_plugin_manifest, orfs_optimization_profile, orfs_plugin_manifest,
    build_seeded_random_control_task, seeded_random_control_plugin_manifest,
    validate_orfs_parameters,
)
from openroad_platform_execution.orfs_config import clock_period_in_platform_units  # noqa: E402
from openroad_platform_scheduler import (  # noqa: E402
    ExternalOptimizerLoopService, PipelineCheckpointStore, RuntimeStore, WorkflowRuntime,
)


COMMON_EVALUATION = "orfs/implementation/analysis/common_evaluation.json"
TERMINAL = {"completed", "diagnosis_required", "failed"}


# These are fixed starting points recorded by the admitted ORFS-Agent source
# (`prompt.md`, and for ASAP7/AES also `exampleaes/config.mk`).  They are not
# tunable knobs in this campaign.  The platform's eight-knob intersection is
# still the only candidate space passed to the upstream GP/EI workbench.
UPSTREAM_ANCHORS: dict[tuple[str, str], dict[str, Any]] = {
    ("asap7", "aes"): {
        "clock_period_ns": .400, "core_utilization_pct": 40,
        "place_density_lb_addon": .3913, "enable_dpo": 1,
        "global_placement_padding": 3, "detail_placement_padding": 3,
        "cts_cluster_size": 20, "cts_cluster_diameter": 100,
        "tns_end_percent": 100,
    },
    ("asap7", "ibex"): {
        "clock_period_ns": 1.260, "core_utilization_pct": 40,
        "place_density_lb_addon": .20, "enable_dpo": 0,
        "tns_end_percent": 100,
    },
    ("asap7", "jpeg"): {
        "clock_period_ns": 1.100, "core_utilization_pct": 30,
        "place_density_lb_addon": .4127, "enable_dpo": 1,
        "tns_end_percent": 100,
    },
    ("sky130hd", "aes"): {
        "clock_period_ns": 4.500, "core_utilization_pct": 20,
        "place_density_lb_addon": .4936, "enable_dpo": 1,
        "tns_end_percent": 100,
    },
    ("sky130hd", "ibex"): {
        "clock_period_ns": 10.000, "core_utilization_pct": 45,
        "place_density_lb_addon": .20, "enable_dpo": 0,
        "tns_end_percent": 100,
    },
    ("sky130hd", "jpeg"): {
        "clock_period_ns": 8.000, "core_utilization_pct": 50,
        "place_density_lb_addon": .15, "enable_dpo": 1,
        "tns_end_percent": 100,
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    temporary.replace(path)


def _command(argv: Sequence[str]) -> str:
    completed = subprocess.run(argv, text=True, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, timeout=60, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(argv)}\n{completed.stdout}")
    return completed.stdout.rstrip()


def _source_receipt(source: Path) -> dict[str, Any]:
    return {
        "repository_source": str(source),
        "commit": _command(("git", "-C", str(source), "rev-parse", "HEAD")),
        "status": _command(("git", "-C", str(source), "status", "--porcelain=v1", "--untracked-files=all")),
        "license_sha256": _sha256(source / "LICENSE"),
    }


def _canonical_evaluation(store: RuntimeStore, run_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    description = store.describe_run(run_id)
    attempts = [attempt for stage in description["stages"] for attempt in stage["attempts"]]
    if len(attempts) != 1:
        raise ValueError(f"expected exactly one Runtime attempt for {run_id}")
    attempt = attempts[0]
    artifact = next((item for item in attempt["artifacts"]
                     if item["store_key"] == COMMON_EVALUATION), None)
    if artifact is None:
        raise ValueError(f"canonical evaluation is missing for successful run {run_id}")
    path = (Path(attempt["workspace"]) / artifact["store_key"]).resolve()
    if not path.is_file() or path.stat().st_size != artifact["size_bytes"] or _sha256(path) != artifact["sha256"]:
        raise ValueError(f"canonical evaluation integrity check failed for {run_id}")
    return json.loads(path.read_text(encoding="utf-8")), artifact


def _candidate_artifact(store: RuntimeStore, run_id: str) -> list[dict[str, Any]]:
    description = store.describe_run(run_id)
    attempts = [attempt for stage in description["stages"] for attempt in stage["attempts"]]
    if len(attempts) != 1 or attempts[0]["status"] != "succeeded":
        raise ValueError("ORFS-Agent Runtime attempt did not succeed")
    attempt = attempts[0]
    artifact = next((item for item in attempt["artifacts"] if item["kind"] == "optimizer_candidates"), None)
    if artifact is None:
        raise ValueError("ORFS-Agent emitted no candidate artifact")
    path = (Path(attempt["workspace"]) / artifact["store_key"]).resolve()
    if not path.is_file() or path.stat().st_size != artifact["size_bytes"] or _sha256(path) != artifact["sha256"]:
        raise ValueError("optimizer candidate artifact integrity check failed")
    value = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(value, Mapping) and isinstance(value.get("candidates"), list):
        value = value["candidates"]
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError("optimizer candidate artifact must be an object list")
    return value


def _freeze_sdc(*, output: Path, source: Path, platform: str,
                period_ns: float) -> Path:
    """Create one immutable campaign SDC before any EDA execution.

    A target clock is a protected experimental input, not a BO action.  The
    upstream reference files express ASAP7 in ps, while platform contracts use
    ns.  We materialize the declared target once in the evidence root and
    refuse to overwrite a previous value.  Every baseline, warm-up and GP/EI
    candidate receives these exact bytes.
    """
    destination = output / "frozen-inputs" / "constraint.sdc"
    destination.parent.mkdir(parents=True, exist_ok=True)
    native = clock_period_in_platform_units(period_ns, platform)
    source_text = source.read_text(encoding="utf-8")
    replaced, count = __import__("re").subn(
        r"(?m)^set\s+clk_period\s+[^\s#]+",
        f"set clk_period {native:g}", source_text,
    )
    if count != 1:
        raise ValueError("reference SDC must contain exactly one set clk_period declaration")
    if destination.exists():
        if destination.read_text(encoding="utf-8") != replaced:
            raise ValueError("existing output has a different frozen timing constraint")
    else:
        destination.write_text(replaced, encoding="utf-8")
    return destination


FORMAL_STAGE_TIMEOUT_SECONDS = 3600
SHARED_PARAMETER_NAMES = (
    "core_utilization_pct", "tns_end_percent", "global_placement_padding",
    "detail_placement_padding", "enable_dpo", "place_density_lb_addon",
    "cts_cluster_size", "cts_cluster_diameter",
)


def _admitted_domain_capacity(domain: Mapping[str, Any], *, platform_name: str) -> int:
    """Count legal finite coordinates before consuming any expensive budget."""
    names = domain.get("search_parameter_names")
    values = domain.get("admissible_values")
    fixed = domain.get("fixed_parameters")
    if not isinstance(names, list) or not isinstance(values, Mapping) or not isinstance(fixed, Mapping):
        raise ValueError("admitted target domain is structurally incomplete")
    if set(names) & set(fixed) or set(names) | set(fixed) != set(SHARED_PARAMETER_NAMES):
        raise ValueError("admitted target domain does not partition the shared ORFS-Agent domain")
    count = 0
    for combination in itertools.product(*(values[name] for name in names)):
        try:
            validate_orfs_parameters({**dict(fixed), **dict(zip(names, combination))},
                                     platform=platform_name)
        except ValueError:
            continue
        count += 1
    return count


def build_argument_parser() -> argparse.ArgumentParser:
    """Return the frozen formal-campaign CLI contract.

    Keeping this construction separate lets the protocol invariant be tested
    without creating a campaign directory or touching an EDA toolchain.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--platform", choices=("asap7", "sky130hd"), required=True)
    parser.add_argument("--design", choices=("aes", "ibex", "jpeg"), required=True)
    parser.add_argument("--orfs-root", type=Path,
                        default=ROOT / "var/toolchains/orfs-51ad1231-clean")
    parser.add_argument("--openroad-bin", type=Path, default=Path.home() / "bin/openroad")
    parser.add_argument("--yosys-bin", type=Path, default=Path.home() / "bin/yosys")
    parser.add_argument("--klayout-bin", type=Path, default=Path.home() / "bin/klayout")
    parser.add_argument("--orfs-agent-source", type=Path,
                        default=ROOT / ".external-src/orfs-agent-admission-20260830-vNWf4x/ORFS-Agent")
    parser.add_argument("--optimizer-arm", choices=("orfs_agent", "seeded_random_control"),
                        default="orfs_agent",
                        help="admitted GP/EI arm or a separately declared equal-budget control arm")
    parser.add_argument("--optimizer-seed", type=int, default=20260830)
    parser.add_argument("--baseline-profile", choices=("upstream_anchor", "platform_default"),
                        default="upstream_anchor")
    parser.add_argument("--target-feasibility-report", type=Path,
                        help=("completed target-design feasibility report required for the "
                              "target-calibrated v2 protocol"))
    parser.add_argument("--warmup-seed", type=int, default=401)
    parser.add_argument("--warmup-count", type=int, default=50)
    parser.add_argument("--candidate-budget", type=int, default=250)
    parser.add_argument("--candidates-per-round", type=int, default=50)
    parser.add_argument("--max-parallel", type=int, default=16)
    parser.add_argument("--orfs-cores-per-run", type=int, default=4)
    # A target-domain value is admitted only after a three-replica preflight
    # using this same per-stage limit.  A shorter formal limit would turn a
    # resource-policy difference into a false optimiser failure.
    parser.add_argument("--stage-timeout", type=int, default=FORMAL_STAGE_TIMEOUT_SECONDS)
    parser.add_argument("--flow-timeout", type=int, default=7200)
    return parser


def main() -> int:
    parser = build_argument_parser()
    args = parser.parse_args()
    if not 8 <= args.warmup_count <= 512:
        parser.error("warmup-count must be 8..512")
    if args.candidate_budget != 5 * args.candidates_per_round:
        parser.error("official-scale alignment requires candidate-budget = five candidate batches")
    if not 2 <= args.candidates_per_round <= 64:
        parser.error("candidates-per-round must be 2..64")
    if not 1 <= args.max_parallel <= 64 or not 1 <= args.orfs_cores_per_run <= 64:
        parser.error("parallelism and cores-per-run must each be 1..64")
    if args.max_parallel * args.orfs_cores_per_run > os.cpu_count():
        parser.error("max-parallel × orfs-cores-per-run exceeds visible CPU budget")
    if args.stage_timeout <= 0 or args.flow_timeout < args.stage_timeout:
        parser.error("flow-timeout must be at least stage-timeout, and both must be positive")

    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    source: Path | None = None
    optimizer_receipt: dict[str, Any]
    if args.optimizer_arm == "orfs_agent":
        source = args.orfs_agent_source.expanduser().resolve()
        receipt = _source_receipt(source)
        if receipt["commit"] != "730f1fa11f9c17c0aaac332412af2b2538f42e9b" or receipt["status"]:
            raise ValueError("ORFS-Agent source must be the clean admitted commit")
        agent_python = ROOT / ".tools/venvs/orfs-agent/bin/python"
        if not agent_python.is_file():
            raise FileNotFoundError("isolated ORFS-Agent Python environment is missing")
        optimizer_receipt = {"kind": "admitted-upstream-gp-ei", "plugin": "orfs-agent@2025.1",
                             "source": receipt}
    else:
        if args.target_feasibility_report is None:
            parser.error("seeded_random_control requires --target-feasibility-report")
        control_python = ROOT / ".tools/venvs/seeded-random-control/bin/python"
        if not control_python.is_file():
            raise FileNotFoundError("isolated seeded Random-control Python environment is missing")
        control_lock = ROOT / "integrations/seeded_random_control/environment.lock.json"
        optimizer_receipt = {
            "kind": "internal-equal-budget-nonadaptive-control",
            "plugin": "seeded-random-control@1.0.0",
            "environment_lock_sha256": _sha256(control_lock),
            "qor_access": False,
        }

    # This is an operator-level resource policy, captured in the run receipt;
    # a web payload cannot increase it.
    os.environ["OPENROAD_PLATFORM_ORFS_CORES"] = str(args.orfs_cores_per_run)
    toolchain = ToolchainConfig(
        name="orfs-agent-paper-campaign",
        orfs_root=args.orfs_root.expanduser().resolve(),
        openroad_bin=args.openroad_bin.expanduser().resolve(),
        yosys_bin=args.yosys_bin.expanduser().resolve(),
        klayout_bin=args.klayout_bin.expanduser().resolve(),
    )
    toolchain.validate()
    reference = load_orfs_reference_design(toolchain.orfs_root,
                                            platform=args.platform, design=args.design)
    profile = orfs_optimization_profile(args.platform)
    anchor = UPSTREAM_ANCHORS[(args.platform, args.design)]
    baseline_parameters = dict(profile["baseline"])
    if args.baseline_profile == "upstream_anchor":
        baseline_parameters.update({name: value for name, value in anchor.items()
                                    if name != "clock_period_ns"})
    # The upstream GP/EI's published common domain starts CTS diameter at 80.
    baseline_parameters["cts_cluster_diameter"] = max(
        float(baseline_parameters.get("cts_cluster_diameter", 80.0)), 80.0)
    if "place_density" in baseline_parameters:
        # ORFS-Agent's shared domain uses LB_ADDON, not PLACE_DENSITY.
        baseline_parameters.pop("place_density")
    admitted_target_domain: dict[str, Any] | None = None
    if args.target_feasibility_report is not None:
        report_path = args.target_feasibility_report.expanduser().resolve()
        report = json.loads(report_path.read_text(encoding="utf-8"))
        admitted_target_domain = derive_target_execution_envelope(
            report, required_parameters=(
                "core_utilization_pct", "tns_end_percent", "global_placement_padding",
                "detail_placement_padding", "enable_dpo", "place_density_lb_addon",
                "cts_cluster_size", "cts_cluster_diameter",
            ), interpolated_steps={
                # These complete integer intervals are exactly representable
                # by the pinned upstream Integer dimensions.  The earlier
                # endpoint-only envelope forced a lossy nearest-value map.
                "core_utilization_pct": "1",
                "tns_end_percent": "1",
                "global_placement_padding": "1",
                "place_density_lb_addon": "0.0001",
            })
        if args.baseline_profile != "upstream_anchor":
            raise ValueError("target-calibrated protocol requires a declared frozen baseline profile")
        report_anchor = admitted_target_domain["flow_anchor"]
        # This is a new campaign, not reuse of v3 measurements: the previously
        # verified complete configuration is frozen as the starting point so
        # the target-domain preflight and formal baseline have one identity.
        baseline_parameters.update(report_anchor)
    frozen_clock_period_ns = (float(anchor["clock_period_ns"])
                              if args.baseline_profile == "upstream_anchor"
                              else reference.clock_period_ns)
    frozen_sdc = _freeze_sdc(output=output, source=reference.sdc_path,
                             platform=args.platform, period_ns=frozen_clock_period_ns)
    replicas, confirmation = (101, 211, 307), (503, 601, 701)
    if admitted_target_domain is not None:
        capacity = _admitted_domain_capacity(admitted_target_domain, platform_name=args.platform)
        required_unique = args.warmup_count + args.candidate_budget + 1  # includes the baseline coordinate
        if capacity < required_unique:
            raise ValueError(
                f"admitted target domain has {capacity} legal coordinates; "
                f"equal-budget protocol requires at least {required_unique} unique coordinates"
            )
    warmup_pool = build_orfs_agent_initial_warmup_recipes(
        platform_name=args.platform, count=args.warmup_count + 1, seed=args.warmup_seed,
        admissible_values=(admitted_target_domain or {}).get("admissible_values"),
        fixed_parameters=(admitted_target_domain or {}).get("fixed_parameters"),
    )
    baseline_shared = {name: baseline_parameters[name] for name in SHARED_PARAMETER_NAMES}
    warmups = [item for item in warmup_pool if item["parameters"] != baseline_shared][:args.warmup_count]
    if len(warmups) != args.warmup_count:
        raise ValueError("could not construct the frozen warm-up set without reusing the baseline coordinate")
    task_id = f"orfs-agent-paper-{args.platform}-{args.design}-baseline"
    main_rtl = next(path for path in reference.rtl_files if path.stem == reference.top)
    base_task = build_orfs_task(
        main_rtl, project_id="orfs-agent-paper", design_id=args.design,
        top=reference.top, clock=reference.clock, platform_name=args.platform,
        target_stage="finish", clock_period_ns=frozen_clock_period_ns,
        core_utilization_pct=float(baseline_parameters["core_utilization_pct"]),
        place_density=float(reference.native_baseline_overrides.get("place_density", .55)),
        or_seed=replicas[0], stage_timeout_seconds=args.stage_timeout,
        timeout_seconds=args.flow_timeout, flow_parameters=baseline_parameters,
        rtl_files=reference.rtl_files, rtl_root=reference.rtl_root,
        rtl_include_dirs=reference.include_dirs,
        synth_hdl_frontend=reference.synth_hdl_frontend,
        design_options=dict(reference.design_options), sdc_path=frozen_sdc,
        task_id=task_id,
        labels={"campaign": "orfs-agent-paper-scale", "reference_design": args.design,
                "design_bundle_sha256": reference.source_fingerprint,
                # Compatibility marker for readers created before the bundle
                # label became the campaign contract.
                "reference_source_sha256": reference.source_fingerprint},
    )
    manifests = [orfs_plugin_manifest(toolchain, default_timeout_seconds=args.flow_timeout)]
    if args.optimizer_arm == "orfs_agent":
        assert source is not None
        manifests.append(orfs_agent_plugin_manifest(source, python_executable=agent_python))
    else:
        manifests.append(seeded_random_control_plugin_manifest(python_executable=control_python))
    store = RuntimeStore(output / "runtime.db")
    runtime = WorkflowRuntime(
        store, PluginRegistry(manifests), workspace_root=output / "attempts",
        worker_id="orfs-agent-paper-campaign", lease_seconds=180,
        protected_evaluator=ORFSProtectedEvaluator(),
    )
    context = LearningContext(
        design_id=args.design, design_fingerprint=reference.source_fingerprint,
        platform=args.platform, pdk_id=args.platform, toolchain_id=reference.orfs_commit,
        flow_stage="finish", metric_parser_version="common_eval_v3",
        constraint_fingerprint=hashlib.sha256(frozen_sdc.read_bytes()).hexdigest(),
    )

    def observation_for_run(run_id: str, _state: Mapping[str, Any]) -> Mapping[str, Any]:
        run = store.get_run(run_id)
        observed = RuntimeEvidenceExporter(store, use_common_evaluation=True).export_run(run_id, context)
        if run.status is not RuntimeStatus.SUCCEEDED:
            return {"observation_id": observed.observation_id, "run_id": run_id,
                    "status": run.status.value, "parameters": dict(observed.parameters),
                    "metrics": dict(observed.metrics),
                    "artifact_refs": [item.ref for item in observed.evidence],
                    "feasible": False, "failure_category": observed.failure_category}
        evaluation, _artifact = _canonical_evaluation(store, run_id)
        return {"observation_id": observed.observation_id, "run_id": run_id,
                "status": observed.status, "parameters": dict(observed.parameters),
                "metrics": dict(observed.metrics),
                "artifact_refs": [item.ref for item in observed.evidence],
                "feasible": bool(evaluation["feasible"]),
                "failure_category": observed.failure_category}

    def optimizer_task(observations: Sequence[Mapping[str, Any]], state: Mapping[str, Any]) -> TaskSpec:
        domain = state.get("admitted_target_domain") or {}
        if args.optimizer_arm == "orfs_agent":
            return build_orfs_agent_native_task(
                project_id="orfs-agent-paper", design_id=args.design, platform_name=args.platform,
                objective="optimizer_objective", observations=observations,
                n_suggestions=int(state["candidates_per_round"]),
                optimizer_seed=int(state["optimizer_seed"]) + int(state.get("round") or 0),
                timeout_seconds=1800,
                search_parameter_names=domain.get("search_parameter_names"),
                fixed_parameters=domain.get("fixed_parameters"),
                admissible_values=domain.get("admissible_values"),
            )
        excluded: list[Mapping[str, Any]] = [state["baseline_parameters"]]
        excluded.extend(item["effective_parameters"] for item in state.get("warmup_runs", [])
                        if isinstance(item, Mapping) and isinstance(item.get("effective_parameters"), Mapping))
        for round_item in state.get("history", []):
            if not isinstance(round_item, Mapping):
                continue
            excluded.extend(item["effective_parameters"] for item in round_item.get("results", [])
                            if isinstance(item, Mapping) and isinstance(item.get("effective_parameters"), Mapping))
        return build_seeded_random_control_task(
            project_id="orfs-agent-paper", design_id=args.design, platform_name=args.platform,
            objective="optimizer_objective", search_parameter_names=domain["search_parameter_names"],
            fixed_parameters=domain["fixed_parameters"], admissible_values=domain["admissible_values"],
            excluded_parameters=excluded, n_suggestions=int(state["candidates_per_round"]),
            seed=int(state["optimizer_seed"]) + int(state.get("round") or 0), timeout_seconds=1800,
        )

    service = ExternalOptimizerLoopService(
        checkpoints=PipelineCheckpointStore(output / "pipeline.db"), runtime=runtime,
        runtime_store=store, observation_for_run=observation_for_run,
        optimizer_task=optimizer_task, candidates_for_run=lambda run_id: _candidate_artifact(store, run_id),
    )
    initial = {
        "status": "baseline_running", "protocol_mode": (
            "target_execution_envelope_external_l2_v3" if admitted_target_domain is not None
            else "paper_comparable_external_l2_v1"),
        "design_id": args.design, "platform": args.platform, "objective_profile": "balanced",
        "optimizer_plugin": optimizer_receipt["plugin"], "base_task": base_task.to_dict(),
        "baseline_parameters": baseline_parameters, "baseline_run_ids": [],
        "replica_or_seeds": list(replicas), "warmup_recipes": warmups, "warmup_runs": [],
        "warmup_seed": args.warmup_seed, "minimum_distinct_feasible_observations": 12,
        "confirmation_seeds": list(confirmation), "optimizer_seed": args.optimizer_seed,
        "max_candidates": args.candidate_budget, "candidates_per_round": args.candidates_per_round,
        "max_parallel": args.max_parallel, "minimum_relative_improvement": .005,
        "frozen_constraints": list(profile["frozen_constraints"]), "round": 0,
        "candidate_count": 0, "stalled_rounds": 0, "history": [], "agent_events": [],
        "allow_stagnation_handoff": False,
        "optimizer_event_claim": (
            "pinned ORFS-Agent GP/EI proposes only allowlisted physical-design vectors"
            if args.optimizer_arm == "orfs_agent"
            else "fixed-seed Random control proposes unseen legal vectors without QoR access"
        ),
        **({"admitted_target_domain": admitted_target_domain}
           if admitted_target_domain is not None else {}),
    }
    receipt_path = output / "campaign-receipt.json"
    campaign_receipt = {
        "schema_version": 1, "status": "running", "claim_boundary": (
            "official-scale ORFS-Agent protocol alignment on a separately pinned ORFS toolchain; "
            "not exact paper-number reproduction until revision/objective equivalence is established"
            if args.optimizer_arm == "orfs_agent" else
            "equal-budget non-adaptive Random control on the same frozen target-domain protocol; "
            "it is a comparator, not an ORFS-Agent reproduction claim"),
        "started_at": datetime.now(timezone.utc).isoformat(), "reference": {
            "platform": args.platform, "design": args.design, "source_fingerprint": reference.source_fingerprint,
            "orfs_commit": reference.orfs_commit, "clock_period_ns": frozen_clock_period_ns,
            "baseline_profile": args.baseline_profile,
            "frozen_sdc": {"path": str(frozen_sdc), "sha256": _sha256(frozen_sdc),
                           "upstream_source_sha256": _sha256(reference.sdc_path)},
        }, "optimizer": optimizer_receipt, "resource_policy": {
            "max_parallel": args.max_parallel, "orfs_cores_per_run": args.orfs_cores_per_run,
            "stage_timeout_seconds": args.stage_timeout,
            "flow_timeout_seconds": args.flow_timeout,
        }, "protocol": {
            "baseline_repetitions": len(replicas), "warmup_count": args.warmup_count,
            "candidate_budget": args.candidate_budget, "candidates_per_round": args.candidates_per_round,
            "confirmation_repetitions": len(confirmation), "minimum_distinct_feasible_observations": 12,
            "required_unique_screening_coordinates": args.warmup_count + args.candidate_budget + 1,
            **({"admitted_legal_coordinate_capacity": capacity} if admitted_target_domain is not None else {}),
        },
        **({"target_feasibility": {
            "path": str(args.target_feasibility_report.expanduser().resolve()),
            "sha256": _sha256(args.target_feasibility_report.expanduser().resolve()),
            "domain_digest": admitted_target_domain["source_domain_digest"],
            "execution_envelope_digest": admitted_target_domain["envelope_digest"],
            "domain_kind": admitted_target_domain["kind"],
            "search_parameter_names": admitted_target_domain["search_parameter_names"],
            "fixed_parameters": admitted_target_domain["fixed_parameters"],
            "verified_values": admitted_target_domain["verified_values"],
            "execution_value_derivations": admitted_target_domain["execution_value_derivations"],
            "flow_anchor": admitted_target_domain["flow_anchor"],
            "fixed_nonshared_flow_parameters": admitted_target_domain[
                "fixed_nonshared_flow_parameters"],
        }} if admitted_target_domain is not None else {}),
    }
    if receipt_path.exists():
        existing = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt_keys = ("reference", "optimizer", "resource_policy", "protocol", "target_feasibility")
        if ({key: existing.get(key) for key in receipt_keys}
                != {key: campaign_receipt.get(key) for key in receipt_keys}):
            raise ValueError("existing output is bound to a different campaign receipt")
    else:
        _atomic_json(receipt_path, campaign_receipt)
    checkpoint = service.create(subject_id=f"orfs-agent-paper-{args.optimizer_arm}-{args.platform}-{args.design}",
                                owner_id=None, initial_state=initial)
    while checkpoint["state"]["status"] not in TERMINAL:
        checkpoint = service.advance(checkpoint["pipeline_id"], execute=True,
                                     max_parallel=args.max_parallel)
        _atomic_json(output / "checkpoint-export.json", checkpoint)
        _atomic_json(output / "heartbeat.json", {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "pipeline_id": checkpoint["pipeline_id"], "status": checkpoint["state"]["status"],
            "round": checkpoint["state"].get("round"),
            "candidate_count": checkpoint["state"].get("candidate_count"),
        })
    campaign_receipt.update({"status": checkpoint["state"]["status"],
                             "ended_at": datetime.now(timezone.utc).isoformat(),
                             "completion_reason": checkpoint["state"].get("completion_reason"),
                             "pipeline_id": checkpoint["pipeline_id"]})
    _atomic_json(receipt_path, campaign_receipt)
    print(json.dumps({"pipeline_id": checkpoint["pipeline_id"],
                      "status": checkpoint["state"]["status"],
                      "completion_reason": checkpoint["state"].get("completion_reason")}))
    return 0 if checkpoint["state"]["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
