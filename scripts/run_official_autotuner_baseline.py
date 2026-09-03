#!/usr/bin/env python3
"""Run a calibrated, clock-frozen official OpenROAD AutoTuner baseline."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import yaml

ROOT = Path(__file__).resolve().parents[1]
for source in (ROOT, *sorted((ROOT / "packages").glob("*/src"))):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from openroad_platform_analysis import (  # noqa: E402
    OfficialAutoTunerInvocation, write_fair_autotuner_bundle,
    evaluate_orfs_run, validate_industrial_dse_protocol,
    write_immutable_evaluation,
)
from openroad_platform_analysis.common_evaluator import SCHEMA_VERSION as EVALUATOR_SCHEMA  # noqa: E402
from openroad_platform_analysis.environment_snapshot import (  # noqa: E402
    combined_python_environment, current_python_environment,
    external_python_environment,
)
from openroad_platform_execution.orfs_parameters import (  # noqa: E402
    ORFS_PARAMETER_BY_NAME, apply_parameter_calibration,
    apply_parameter_search_allowlist,
    official_autotuner_independent_parameter_names,
    orfs_optimization_profile,
)
from openroad_platform_execution import (  # noqa: E402
    generated_design_from_platform_plan, generated_design_from_reference_design,
    load_orfs_reference_design,
    validate_pinned_orfs_toolchain,
)


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _git_commit(path: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def _source_tree_sha256(path: Path) -> str:
    rows = []
    for item in sorted(path.rglob("*")):
        if item.is_file() and "__pycache__" not in item.parts:
            rows.append({
                "path": str(item.relative_to(path)),
                "sha256": hashlib.sha256(item.read_bytes()).hexdigest(),
            })
    return hashlib.sha256(json.dumps(
        rows, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


def _controller_source_snapshot() -> dict:
    """Hash all local Python code that may influence common evaluation."""
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
    digest = hashlib.sha256(json.dumps(
        records, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    return {"digest": digest, "file_count": len(records), "files": records}


def _trial_results(artifact_root: Path) -> list[dict]:
    rows = []
    for path in sorted(artifact_root.glob("variant-*-ray/result.json")):
        last = None
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                last = json.loads(line)
            except json.JSONDecodeError:
                continue
        if last is None:
            rows.append({"path": str(path), "status": "unreadable"})
            continue
        metric = last.get("metric")
        params_path = path.with_name("params.json")
        try:
            parameters = json.loads(params_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            parameters = None
        accepted = (isinstance(metric, (int, float)) and math.isfinite(float(metric))
                    and float(metric) < 1e90)
        rows.append({
            "path": str(path), "trial_id": last.get("trial_id"),
            "timestamp": last.get("timestamp"),
            "time_total_s": last.get("time_total_s"),
            "metric": metric, "effective_clk_period": last.get("effective_clk_period"),
            "num_drc": last.get("num_drc"), "die_area": last.get("die_area"),
            "parameters": parameters,
            "accepted_by_upstream_metric": accepted,
        })
    return sorted(rows, key=lambda item: (
        float(item["timestamp"]) if isinstance(item.get("timestamp"), (int, float))
        else math.inf,
        str(item.get("trial_id") or item.get("path")),
    ))


def _annotate_warm_start(trials: list[dict], baseline_point: dict) \
        -> tuple[list[dict], list[str]]:
    """Separate one free baseline observation from charged candidates."""
    def same(left: object, right: object) -> bool:
        if (isinstance(left, (int, float)) and not isinstance(left, bool)
                and isinstance(right, (int, float)) and not isinstance(right, bool)):
            return math.isclose(float(left), float(right), rel_tol=0, abs_tol=1e-12)
        return left == right

    matches = []
    for index, trial in enumerate(trials):
        parameters = trial.get("parameters")
        if (isinstance(parameters, dict) and set(parameters) == set(baseline_point)
                and all(same(parameters[key], baseline_point[key])
                        for key in baseline_point)):
            matches.append(index)
    errors = []
    if len(matches) != 1:
        errors.append(
            f"expected exactly one uncharged baseline warm-start trial, found {len(matches)}")
    logical_round = 0
    rows = []
    for index, trial in enumerate(trials):
        row = dict(trial)
        if len(matches) == 1 and index == matches[0]:
            row.update({"budget_role": "warm_start_baseline", "logical_round": None})
        else:
            logical_round += 1
            row.update({"budget_role": "logical_candidate",
                        "logical_round": logical_round})
        rows.append(row)
    return rows, errors


def _official_tunable_variables(orfs_root: Path) -> set[str]:
    source = orfs_root / "flow/scripts/variables.yaml"
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    return {str(name) for name, row in data.items()
            if isinstance(row, dict) and row.get("tunable", 0) == 1}


def _validated_runtime_seconds(value: object, *, source: str) -> float:
    """Return a finite positive wall time or fail the evidence contract."""
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(float(value)) or float(value) <= 0):
        raise ValueError(f"missing or invalid runtime evidence from {source}")
    return float(value)


def _common_evaluate_trials(*, trials: list[dict], artifact_root: Path,
                            output: Path, orfs_root: Path, platform: str,
                            logical_design: str, execution_design: str,
                            generated_design: dict,
                            fairness_config_sha256: str, optimizer_seed: int,
                            or_seeds: list[int], openroad_threads: int,
                            timeout_hours: float,
                            controlled_environment: dict[str, str]) -> list[dict]:
    """Re-score upstream trials with the exact native-platform evidence gate."""
    rows = []
    experiment = artifact_root.name
    result_root = (orfs_root / "flow/results" / platform /
                   execution_design / experiment)
    allowed_variables = _official_tunable_variables(orfs_root)
    for trial in trials:
        row = dict(trial)
        if row.get("budget_role") == "warm_start_baseline":
            row["common_evaluations"] = []
            row["common_evaluation"] = {
                "status": "not_required_uncharged_warm_start",
                "reason": "Native common-evaluator baseline evidence is paired separately.",
                "paired_or_seeds": or_seeds, "replica_count": 0,
                "all_feasible": False,
            }
            rows.append(row)
            continue
        if row.get("accepted_by_upstream_metric") is not True:
            row["common_evaluations"] = []
            row["common_evaluation"] = {
                "status": "not_required_upstream_rejected",
                "reason": (
                    "The optimizer consumed this logical budget item as a failed trial; "
                    "it remains infeasible and is not replayed."
                ),
                "paired_or_seeds": or_seeds,
                "replica_count": 0,
                "all_feasible": False,
            }
            rows.append(row)
            continue
        trial_id = str(row.get("trial_id") or "")
        leaves = sorted(artifact_root.glob(
            f"variant-AutoTunerBase-{trial_id}-or-*")) if trial_id else []
        if len(leaves) != 1:
            row["common_evaluation"] = {
                "status": "unavailable", "reason":
                    f"expected exactly one ORFS leaf, found {len(leaves)}"}
            rows.append(row); continue
        ray_result = Path(str(row["path"]))
        params_path = ray_result.with_name("params.json")
        params = row.get("parameters")
        if not isinstance(params, dict):
            params = (json.loads(params_path.read_text(encoding="utf-8"))
                      if params_path.is_file() else {})
        unsafe = [key for key in params if (
            key not in allowed_variables or
            not re.fullmatch(r"[A-Z][A-Z0-9_]*", str(key)) or
            any(token in str(key) for token in ("SDC", "CLOCK", "CLK_PERIOD")))]
        if unsafe:
            row["common_evaluation"] = {
                "status": "unavailable",
                "reason": f"unsafe or non-common trial variables: {unsafe}",
            }
            rows.append(row); continue
        evaluations = []
        for seed_index, or_seed in enumerate(or_seeds):
            if seed_index == 0:
                log_dir = leaves[0]
                result_dir = result_root / leaves[0].name
                runtime_seconds = _validated_runtime_seconds(
                    row.get("time_total_s"), source="ray_result.time_total_s")
                replay = {"kind": "upstream_trial", "returncode": 0,
                          "log_dir": str(log_dir), "result_dir": str(result_dir),
                          "runtime_seconds": runtime_seconds,
                          "runtime_source": "ray_result.time_total_s"}
            else:
                variant = (f"{experiment}-paired-replay/"
                           f"variant-{trial_id}-s{or_seed}")
                log_dir = (orfs_root / "flow/logs" / platform /
                           execution_design / variant)
                result_dir = (orfs_root / "flow/results" / platform /
                              execution_design / variant)
                command = [
                    "make", "-C", str(orfs_root / "flow"),
                    (f"DESIGN_CONFIG=designs/{platform}/"
                     f"{execution_design}/config.mk"),
                    f"PLATFORM={platform}", f"FLOW_VARIANT={variant}",
                    "EQUIVALENCE_CHECK=0", "LEC_CHECK=0",
                    f"NUM_CORES={openroad_threads}", f"OR_SEED={or_seed}",
                    *[f"{key}={value}" for key, value in sorted(params.items())],
                ]
                environment = dict(os.environ)
                environment.update(controlled_environment)
                replay_log = output / "paired-replay-logs" / f"{trial_id}-s{or_seed}.log"
                replay_log.parent.mkdir(parents=True, exist_ok=True)
                timed_out = False
                replay_started = time.monotonic()
                try:
                    with replay_log.open("w", encoding="utf-8") as stream:
                        completed = subprocess.run(
                            command, env=environment, stdout=stream,
                            stderr=subprocess.STDOUT, check=False,
                            timeout=max(60, int(timeout_hours * 3600)),
                        )
                    replay_returncode = completed.returncode
                except subprocess.TimeoutExpired:
                    timed_out = True
                    replay_returncode = None
                runtime_seconds = _validated_runtime_seconds(
                    time.monotonic() - replay_started,
                    source="controller_monotonic_wall_clock")
                replay = {
                    "kind": "paired_full_replay", "returncode": replay_returncode,
                    "timed_out": timed_out,
                    "command": command, "controller_log": str(replay_log),
                    "controller_log_sha256": hashlib.sha256(
                        replay_log.read_bytes()).hexdigest(),
                    "runtime_seconds": runtime_seconds,
                    "runtime_source": "controller_monotonic_wall_clock",
                    "log_dir": str(log_dir), "result_dir": str(result_dir),
                }
            effective_sha = hashlib.sha256(json.dumps({
                "fairness_config_sha256": fairness_config_sha256,
                "trial_parameters": params, "or_seed": or_seed,
                "design_identity_sha256": generated_design.get(
                    "comparison_identity_sha256",
                    generated_design["identity_sha256"],
                ),
            }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            try:
                evaluation = evaluate_orfs_run(
                    log_dir=log_dir, result_dir=result_dir,
                    platform=platform, design=logical_design,
                    design_identity_sha256=generated_design.get(
                        "comparison_identity_sha256",
                        generated_design["identity_sha256"],
                    ),
                    effective_config_sha256=effective_sha, or_seed=or_seed,
                    source_kind="official-openroad-autotuner-hyperopt",
                    clock_period_ns=float(generated_design["clock_period_ns"]),
                    runtime_seconds=runtime_seconds,
                    run_metadata={
                        "optimizer_seed": optimizer_seed, "trial_id": trial_id,
                        "upstream_result": str(ray_result), "trial_parameters": params,
                        "replay": replay,
                    },
                )
                evaluation_path = (output / "common-evaluations" /
                                   f"{trial_id}-s{or_seed}-e{EVALUATOR_SCHEMA}.json")
                write_immutable_evaluation(evaluation_path, evaluation)
                evaluations.append({
                    "status": "completed", "path": str(evaluation_path),
                    "evaluation_id": evaluation["evaluation_id"],
                    "or_seed": or_seed, "feasible": evaluation["feasible"],
                    "metrics": evaluation["metrics"], "replay": replay,
                })
            except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
                evaluations.append({
                    "status": "failed", "or_seed": or_seed,
                    "reason": str(exc)[:500], "replay": replay,
                })
        row["common_evaluations"] = evaluations
        row["common_evaluation"] = {
            "status": ("completed" if len(evaluations) == len(or_seeds)
                       and all(item["status"] == "completed" for item in evaluations)
                       else "incomplete"),
            "paired_or_seeds": or_seeds,
            "replica_count": len(evaluations),
            "all_feasible": bool(evaluations) and all(
                item.get("feasible") is True for item in evaluations),
        }
        rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=
                        ROOT / "studies/protocols/v2-industrial-dse-20260829-r27.protocol.json")
    parser.add_argument("--mode", choices=("preflight", "paper"), default="paper")
    parser.add_argument("--calibration", type=Path, default=
                        ROOT / "var/calibration/orfs-parameters-v2/parameter_calibration_report.json")
    parser.add_argument("--orfs-root", type=Path,
                        default=ROOT / "var/toolchains/orfs-51ad1231-clean")
    parser.add_argument("--toolchain-lock", type=Path, default=
                        ROOT / "integrations/orfs/orfs-industrial-v2.lock.json")
    parser.add_argument("--autotuner-root", type=Path,
                        help="Defaults to tools/AutoTuner inside the pinned ORFS worktree")
    parser.add_argument("--python", type=Path, default=
                        ROOT / ".tools/venvs/orfs-autotuner/bin/python")
    parser.add_argument("--openroad-wrapper", type=Path,
                        default=Path.home() / "bin/openroad")
    parser.add_argument("--yosys-wrapper", type=Path,
                        default=Path.home() / "bin/yosys")
    parser.add_argument("--platform", required=True,
                        choices=("nangate45", "asap7", "sky130hd"))
    parser.add_argument("--design")
    parser.add_argument("--reference-design", choices=("aes", "jpeg", "ibex"),
                        help="Use the server-pinned ORFS reference recipe and source fingerprint")
    parser.add_argument(
        "--generated-plan", type=Path,
        help="ORFSRunner plan.json whose exact RTL/SDC/configuration is installed for a fair comparison",
    )
    parser.add_argument(
        "--allow-native-design-smoke", action="store_true",
        help="Permit an ORFS-native design for plumbing smoke tests only; never a fair paper result",
    )
    parser.add_argument("--algorithm", default="hyperopt",
                        choices=("random", "hyperopt", "optuna", "ax"))
    parser.add_argument("--samples", type=int, required=True)
    parser.add_argument("--optimizer-seed", type=int, required=True)
    parser.add_argument("--or-seed", type=int, required=True)
    parser.add_argument("--paired-or-seeds", default="101,211,307",
                        help="Ordered full-flow replay seeds; first seed drives upstream search")
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--openroad-threads", type=int, default=6)
    parser.add_argument("--stop-stage", default="finish",
                        choices=("floorplan", "place", "cts", "globalroute", "route", "finish"))
    parser.add_argument("--timeout-hours", type=float, default=4.0)
    parser.add_argument("--experiment")
    parser.add_argument("--expected-runner-sha256")
    parser.add_argument("--expected-controller-source-sha256")
    parser.add_argument("--expected-python-environment-sha256")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    runner_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if (args.expected_runner_sha256
            and runner_sha256 != args.expected_runner_sha256):
        parser.error("official runner changed after the campaign manifest was frozen")
    controller_source_snapshot = _controller_source_snapshot()
    if (args.expected_controller_source_sha256
            and controller_source_snapshot["digest"] !=
            args.expected_controller_source_sha256):
        parser.error(
            "official evaluator source changed after the campaign manifest was frozen")
    python_environment = combined_python_environment(
        controller=current_python_environment(),
        external=external_python_environment(args.python),
    )
    if (args.expected_python_environment_sha256
            and python_environment["fingerprint"] !=
            args.expected_python_environment_sha256):
        parser.error("official Python environments changed after campaign freeze")

    try:
        paired_or_seeds = [int(item) for item in args.paired_or_seeds.split(",")]
    except ValueError:
        parser.error("paired-or-seeds must be comma-separated integers")
    if (not 2 <= len(paired_or_seeds) <= 8
            or len(set(paired_or_seeds)) != len(paired_or_seeds)
            or paired_or_seeds[0] != args.or_seed
            or any(not 1 <= item <= 2_147_483_647 for item in paired_or_seeds)):
        parser.error("paired-or-seeds requires 2..8 distinct positive seeds starting with --or-seed")
    protocol = json.loads(
        args.protocol.expanduser().resolve().read_text(encoding="utf-8"))
    validate_industrial_dse_protocol(protocol)
    if args.mode == "paper":
        primary_blocks = {(item["platform"], item["design"])
                          for item in protocol["primary_blocks"]}
        if args.reference_design is None:
            parser.error("paper mode requires a server-pinned --reference-design")
        if (args.platform, args.reference_design) not in primary_blocks:
            parser.error("paper reference block is outside the frozen protocol")
        if args.algorithm != "hyperopt":
            parser.error("paper mode requires the preregistered official Hyperopt arm")
        if args.samples != max(protocol["budget_checkpoints"]):
            parser.error("paper AutoTuner must run the maximum frozen budget")
        if args.optimizer_seed not in protocol["optimizer_seeds"]:
            parser.error("optimizer seed is outside the frozen protocol")
        if paired_or_seeds != protocol["paired_or_seeds"]:
            parser.error("paired OR_SEED vector differs from the frozen protocol")
        if args.experiment is not None:
            parser.error("paper mode derives an immutable experiment namespace")

    orfs_root = args.orfs_root.expanduser().resolve()
    autotuner_root = (args.autotuner_root.expanduser().resolve()
                      if args.autotuner_root else
                      orfs_root / "tools/AutoTuner")
    autotuner_source = autotuner_root / "src"
    if not (autotuner_source / "autotuner/distributed.py").is_file():
        parser.error("pinned AutoTuner Python source is missing")
    try:
        toolchain_validation = validate_pinned_orfs_toolchain(
            orfs_root, args.toolchain_lock.expanduser().resolve())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(f"pinned toolchain validation failed: {exc}")
    selected_design_modes = sum((
        args.generated_plan is not None,
        args.reference_design is not None,
        bool(args.allow_native_design_smoke),
    ))
    if selected_design_modes != 1:
        parser.error("select exactly one of --generated-plan, --reference-design, or --allow-native-design-smoke")

    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    output_lock = (output / "official-autotuner.lock").open("a+")
    try:
        fcntl.flock(output_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("official AutoTuner cell already has an active controller", file=sys.stderr)
        return 2
    report = json.loads(args.calibration.expanduser().resolve().read_text(encoding="utf-8"))
    profile = apply_parameter_calibration(orfs_optimization_profile(args.platform), report)
    reference = None
    if args.reference_design is not None:
        reference = load_orfs_reference_design(
            orfs_root, platform=args.platform, design=args.reference_design)
        reference_flow_baseline = {
            key: value for key, value in reference.native_baseline_overrides.items()
            if key != "place_density"
        }
        profile = {
            **profile,
            "baseline": {**profile["baseline"], **reference_flow_baseline},
        }
    env_names = {name: ORFS_PARAMETER_BY_NAME[name].env_name
                 for name in profile["baseline"]}
    supported_env_names = _official_tunable_variables(orfs_root)
    common_names = official_autotuner_independent_parameter_names(
        profile, orfs_root / "flow/scripts/variables.yaml")
    profile = apply_parameter_search_allowlist(
        profile, common_names, domain_id="official_autotuner_independent_v2")
    baseline_point = {
        env_names[name]: (int(profile["baseline"][name])
                          if isinstance(profile["baseline"][name], bool)
                          else profile["baseline"][name])
        for name in sorted(common_names)
    }

    if args.reference_design is not None:
        assert reference is not None
        if args.design and args.design != reference.design:
            parser.error("--design must match --reference-design when both are supplied")
        logical_design = reference.design
        generated_design = generated_design_from_reference_design(
            reference, orfs_root=orfs_root,
            flow_parameters=profile["baseline"], or_seed=args.or_seed,
            autotuner_initial_points=(baseline_point,),
        )
        execution_design = generated_design["namespace"]
    elif args.generated_plan is None:
        if not args.design:
            parser.error("--design is required with --allow-native-design-smoke")
        generated_design = None
        logical_design = args.design
        execution_design = args.design
    else:
        if args.allow_native_design_smoke:
            parser.error("--allow-native-design-smoke cannot be combined with --generated-plan")
        generated_design = generated_design_from_platform_plan(
            args.generated_plan, orfs_root=orfs_root,
            autotuner_initial_points=(baseline_point,))
        if generated_design["platform"] != args.platform:
            parser.error("generated plan platform does not match --platform")
        if int(generated_design["or_seed"]) != args.or_seed:
            parser.error("generated plan OR_SEED does not match --or-seed")
        if args.design and args.design != generated_design["top"]:
            parser.error("--design must match the generated plan top when both are supplied")
        logical_design = str(args.design or generated_design["top"])
        execution_design = generated_design["namespace"]

    bundle = write_fair_autotuner_bundle(
        output / "fair-config", profile, or_seed=args.or_seed, env_names=env_names,
        domain_id="official_autotuner_independent_v2",
        supported_env_names=supported_env_names)
    experiment = args.experiment or (
        f"v2-{args.mode}-{protocol['protocol_digest'][:10]}-{args.platform}-"
        f"{logical_design}-{args.algorithm}-o{args.optimizer_seed}-"
        f"r{args.or_seed}-b{args.samples}")
    artifact_root = (orfs_root / "flow/logs" / args.platform / execution_design /
                     f"{experiment}-tune")
    resume = artifact_root.is_dir() and any(
        artifact_root.glob("experiment_state-*.json"))
    invocation = OfficialAutoTunerInvocation(
        # Preserve the venv interpreter path; resolving this symlink turns it
        # into /usr/bin/python and silently drops the isolated dependencies.
        python=os.path.abspath(args.python.expanduser()),
        autotuner_root=str(autotuner_root),
        orfs_root=str(orfs_root),
        design=execution_design, platform=args.platform,
        config_path=bundle["config_path"], experiment=experiment,
        algorithm=args.algorithm, samples=args.samples + 1,
        optimizer_seed=args.optimizer_seed, jobs=args.jobs,
        openroad_threads=args.openroad_threads, stop_stage=args.stop_stage,
        timeout_hours=args.timeout_hours,
        resume=resume,
    )
    controlled = invocation.controlled_environment(
        openroad_wrapper=str(args.openroad_wrapper),
        yosys_wrapper=str(args.yosys_wrapper),
        fixed_flow_environment=bundle["fixed_flow_environment"])
    # The venv may have been installed editable from a developer checkout.
    # PYTHONPATH forces the module bytes to come from the validated pinned
    # ORFS commit instead of trusting that mutable installation pointer.
    controlled["PYTHONPATH"] = str(autotuner_source)
    manifest = invocation.manifest(
        environment=controlled, upstream_commit=_git_commit(orfs_root),
        generated_design=generated_design)
    manifest.update({
        "created_at": datetime.now(timezone.utc).isoformat(),
        "fairness_bundle": bundle,
        "calibration_path": str(args.calibration.expanduser().resolve()),
        "calibration_report_sha256": __import__("hashlib").sha256(
            args.calibration.expanduser().resolve().read_bytes()).hexdigest(),
        "comparison_eligible": generated_design is not None,
        "common_evaluator_schema": EVALUATOR_SCHEMA,
        "toolchain_validation": toolchain_validation,
        "autotuner_source_root": str(autotuner_source),
        "autotuner_source_sha256": _source_tree_sha256(autotuner_source),
        "controller_source_snapshot_sha256":
            controller_source_snapshot["digest"],
        "python_environment_fingerprint": python_environment["fingerprint"],
        "frozen_study_protocol_digest": protocol["protocol_digest"],
        "study_mode": args.mode,
        "experiment_namespace": experiment,
        "logical_candidate_budget": args.samples,
        "uncharged_warm_start_count": 1,
        "upstream_sample_count": args.samples + 1,
        "resume_requested": resume,
        "claim_boundary": (
            "This invokes the official external optimizer on the calibrated common domain. "
            + ("The generated-design adapter pins the same RTL and SDC bytes. "
               if generated_design is not None else
               "Native-design mode is a plumbing smoke test and is not comparison evidence. ")
            + "Superiority claims require common-evaluator full-flow replay and repeated seeds."
        ),
    })
    binding = {
        "schema_version": 1, "kind": "official-autotuner-cell-binding",
        "platform": args.platform, "design": logical_design,
        "execution_design": execution_design,
        "algorithm": args.algorithm, "samples": args.samples,
        "upstream_samples": args.samples + 1,
        "uncharged_warm_start_count": 1,
        "optimizer_seed": args.optimizer_seed, "or_seed": args.or_seed,
        "paired_or_seeds": paired_or_seeds,
        "stop_stage": args.stop_stage,
        "generated_design_identity_sha256": (
            generated_design["identity_sha256"] if generated_design else None),
        "generated_design_sdc_sha256": (
            generated_design["sdc_sha256"] if generated_design else None),
        "fairness_config_sha256": bundle["config_sha256"],
        "search_domain_id": bundle["domain_id"],
        "search_parameter_names": bundle["selected_parameter_names"],
        "parameter_domain_fingerprint": bundle["parameter_domain_fingerprint"],
        "fairness_manifest_fingerprint": bundle["manifest_fingerprint"],
        "calibration_report_sha256": manifest["calibration_report_sha256"],
        "common_evaluator_schema": EVALUATOR_SCHEMA,
        "upstream_commit": manifest.get("upstream_commit"),
        "toolchain_validation_fingerprint": toolchain_validation[
            "validation_fingerprint"],
        "toolchain_lock_sha256": toolchain_validation["lock_sha256"],
        "autotuner_source_sha256": manifest["autotuner_source_sha256"],
        "runner_sha256": runner_sha256,
        "controller_source_snapshot_sha256": controller_source_snapshot["digest"],
        "python_environment_fingerprint": python_environment["fingerprint"],
        "frozen_study_protocol_digest": protocol["protocol_digest"],
        "study_mode": args.mode,
        "experiment_namespace": experiment,
    }
    binding_path = output / "cell-binding.json"
    if binding_path.exists():
        if json.loads(binding_path.read_text(encoding="utf-8")) != binding:
            print("official AutoTuner output is bound to another protocol", file=sys.stderr)
            return 2
    else:
        _atomic_json(binding_path, binding)
    if args.mode == "preflight":
        _atomic_json(output / "EXCLUDED_FROM_FORMAL_STUDY.json", {
            "excluded": True,
            "reason": "preflight mode is engineering evidence, not a preregistered paper cell",
            "study_mode": args.mode,
            "protocol_digest": protocol["protocol_digest"],
        })
    _atomic_json(output / "controller-source-snapshot.json",
                 controller_source_snapshot)
    _atomic_json(output / "python-environment.json", python_environment)
    attempts = output / "controller-attempts"
    attempts.mkdir(parents=True, exist_ok=True)
    attempt_index = len(list(attempts.glob("attempt-*-invocation.json"))) + 1
    manifest["controller_attempt"] = attempt_index
    _atomic_json(attempts / f"attempt-{attempt_index:04d}-invocation.json", manifest)
    _atomic_json(output / "invocation-manifest.json", manifest)
    if args.dry_run:
        print(json.dumps({"manifest": str(output / "invocation-manifest.json"),
                          "command": list(invocation.command())}, indent=2))
        return 0

    log_path = output / "controller.log"
    environment = dict(os.environ); environment.update(controlled)
    started_at = datetime.now(timezone.utc).isoformat()
    with log_path.open("w", encoding="utf-8") as log:
        completed = subprocess.run(
            invocation.command(), cwd=invocation.working_directory(),
            env=environment, stdout=log, stderr=subprocess.STDOUT, check=False)
    artifact_root = Path(manifest["artifact_root"])
    trials = _trial_results(artifact_root)
    warm_start_errors = []
    if generated_design is not None:
        trials, warm_start_errors = _annotate_warm_start(trials, baseline_point)
    if generated_design is not None and not warm_start_errors:
        trials = _common_evaluate_trials(
            trials=trials, artifact_root=artifact_root, output=output,
            orfs_root=orfs_root, platform=args.platform,
            logical_design=logical_design, execution_design=execution_design,
            generated_design=generated_design,
            fairness_config_sha256=bundle["config_sha256"],
            optimizer_seed=args.optimizer_seed, or_seeds=paired_or_seeds,
            openroad_threads=args.openroad_threads,
            timeout_hours=args.timeout_hours,
            controlled_environment=controlled,
        )
    successful = [row for row in trials if row.get("accepted_by_upstream_metric")]
    logical_trials = [row for row in trials
                      if row.get("budget_role") == "logical_candidate"]
    successful_logical = [row for row in logical_trials
                          if row.get("accepted_by_upstream_metric")]
    result = {
        "schema_version": 1,
        "kind": "official-openroad-autotuner-baseline-result",
        "started_at": started_at, "ended_at": datetime.now(timezone.utc).isoformat(),
        "returncode": completed.returncode, "controller_log": str(log_path),
        "artifact_root": str(artifact_root), "trials": trials,
        "trial_count": len(trials), "successful_trial_count": len(successful),
        "logical_trial_count": len(logical_trials),
        "successful_logical_trial_count": len(successful_logical),
        "warm_start_trial_count": sum(
            row.get("budget_role") == "warm_start_baseline" for row in trials),
        "warm_start_errors": warm_start_errors,
        "status": ("succeeded" if completed.returncode in {0, 16}
                   and not warm_start_errors else "failed"),
        "common_evaluator_pending": generated_design is None,
        "common_evaluated_trial_count": sum(
            (row.get("common_evaluation") or {}).get("status") == "completed"
            for row in trials),
        "common_feasible_trial_count": sum(
            (row.get("common_evaluation") or {}).get("all_feasible") is True
            for row in trials),
        "claim_boundary": (
            "Upstream success is only an execution gate. QoR comparisons use immutable "
            "ORFS artifacts, the common evaluator, paired seeds, and full-flow replay."
        ),
    }
    _atomic_json(output / "result.json", result)
    print(json.dumps({"result": str(output / "result.json"),
                      "status": result["status"], "trials": len(trials),
                      "successful": len(successful)}))
    return 0 if result["status"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
