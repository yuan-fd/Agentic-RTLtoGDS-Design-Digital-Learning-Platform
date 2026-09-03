"""Auditable compatibility boundary for the upstream ORFS AutoTuner.

The upstream tool remains an external paper baseline.  This module only
creates a fairness-constrained configuration and an invocation manifest; it
does not copy AutoTuner into the platform's product optimizer.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


FORBIDDEN_CONSTRAINT_TOKENS = (
    "SDC", "CLK_PERIOD", "CLOCK_PERIOD", "UNCERTAINTY", "IO_DELAY",
)
SUPPORTED_ALGORITHMS = ("random", "hyperopt", "optuna", "ax")


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _parameter_entry(spec: Mapping[str, Any], env_name: str) -> dict[str, Any]:
    kind = str(spec["kind"])
    if kind == "bool":
        choices = tuple(spec.get("choices") or (0, 1))
        if choices != (0, 1):
            raise ValueError(f"AutoTuner adapter only supports binary bools: {env_name}")
        # Pinned AutoTuner maps step-1 integers to Ray ``randint(min, max)``;
        # its upper bound is exclusive while ParameterSpec.upper is inclusive.
        return {"type": "int", "minmax": [0, 2], "step": 1}
    if kind == "categorical":
        choices = list(spec.get("choices") or ())
        if not choices:
            raise ValueError(f"categorical parameter has no choices: {env_name}")
        return {"type": "string", "values": choices}
    if kind not in {"int", "float"}:
        raise ValueError(f"unsupported AutoTuner parameter kind: {kind}")
    lower, upper = spec.get("lower"), spec.get("upper")
    if lower is None or upper is None or float(lower) > float(upper):
        raise ValueError(f"invalid range for {env_name}")
    step = spec.get("step") or 0
    # For every quantized numeric domain, pinned AutoTuner uses either
    # ``randint`` or ``np.arange`` and therefore excludes the configured upper
    # bound. Encode one step beyond the platform's inclusive upper bound so
    # the enumerated value set is byte-for-byte equal across comparison arms.
    encoded_upper = (float(upper) + float(step)) if step else upper
    return {
        "type": kind,
        "minmax": ([int(lower), int(round(encoded_upper))] if kind == "int"
                   else [float(lower), float(encoded_upper)]),
        "step": int(step) if kind == "int" else float(step),
    }


def build_fair_autotuner_config(
    calibrated_profile: Mapping[str, Any], *, or_seed: int,
    env_names: Mapping[str, str], domain_id: str,
    supported_env_names: Iterable[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Translate one subtractively calibrated platform profile.

    ``OR_SEED`` is fixed rather than searched, separating implementation noise
    from optimizer randomness.  Clock and SDC variables are rejected.
    """
    if not 1 <= int(or_seed) <= 2**31 - 1:
        raise ValueError("OR_SEED must be a positive 32-bit integer")
    if not domain_id or not domain_id.replace("_", "").replace("-", "").isalnum():
        raise ValueError("AutoTuner fairness domain_id must be a safe identifier")
    calibration = calibrated_profile.get("parameter_calibration") or {}
    eligible = set(calibration.get("search_eligible") or ())
    specs = tuple(calibrated_profile.get("parameter_space") or ())
    if not eligible or eligible != {str(item["name"]) for item in specs}:
        raise ValueError("profile must already be filtered by parameter calibration")
    supported = (set(supported_env_names) if supported_env_names is not None else None)
    config: dict[str, Any] = {}
    mapping = []
    excluded = []
    # Match the product runner's explicit execution contract. The pinned ORFS
    # tree contains a partial kepler-formal install whose dynamic libraries are
    # absent; LEC is a separate validation gate and must not make DSE trials
    # fail after successful CTS.
    fixed_environment = {"OR_SEED": int(or_seed), "LEC_CHECK": 0}
    for spec in specs:
        name = str(spec["name"])
        env_name = str(env_names.get(name) or "")
        if not env_name:
            raise ValueError(f"missing ORFS environment mapping for {name}")
        if any(token in env_name.upper() for token in FORBIDDEN_CONSTRAINT_TOKENS):
            raise ValueError(f"constraint-changing parameter is forbidden: {env_name}")
        if supported is not None and env_name not in supported:
            if name not in calibrated_profile.get("baseline", {}):
                raise ValueError(f"excluded official parameter has no fixed baseline: {name}")
            fixed_environment[env_name] = calibrated_profile["baseline"][name]
            excluded.append({
                "platform_parameter": name,
                "orfs_environment_variable": env_name,
                "reason": "not_marked_tunable_by_pinned_official_autotuner",
                "fixed_value": calibrated_profile["baseline"][name],
            })
            continue
        if env_name in config:
            raise ValueError(f"duplicate AutoTuner environment variable: {env_name}")
        config[env_name] = _parameter_entry(spec, env_name)
        mapping.append({
            "platform_parameter": name,
            "orfs_environment_variable": env_name,
            "kind": spec["kind"], "stage": spec.get("stage"),
            "range": [spec.get("lower"), spec.get("upper")],
            "platform_bound_semantics": "inclusive",
            "upstream_config_upper_semantics": (
                "exclusive_encoded_one_step_above" if spec.get("step")
                else "continuous_exclusive_measure_zero_difference"),
            "choices": list(spec.get("choices") or ()),
            "step": spec.get("step"),
        })
    searched_names = {str(item["name"]) for item in specs}
    for name, value in sorted(dict(
            calibrated_profile.get("fixed_parameters") or {}).items()):
        if name in searched_names:
            continue
        env_name = str(env_names.get(name) or "")
        if not env_name:
            raise ValueError(f"missing ORFS environment mapping for fixed parameter {name}")
        if any(token in env_name.upper() for token in FORBIDDEN_CONSTRAINT_TOKENS):
            raise ValueError(f"constraint-changing fixed parameter is forbidden: {env_name}")
        if env_name in config or env_name in fixed_environment:
            raise ValueError(f"duplicate fixed AutoTuner environment variable: {env_name}")
        if isinstance(value, bool):
            value = int(value)
        if not isinstance(value, (str, int, float)):
            raise ValueError(f"fixed AutoTuner value must be scalar: {name}")
        fixed_environment[env_name] = value
        excluded.append({
            "platform_parameter": name,
            "orfs_environment_variable": env_name,
            "reason": "fixed_by_subtractive_common_domain",
            "fixed_value": value,
        })
    if not mapping:
        raise ValueError("official AutoTuner common parameter intersection is empty")
    selected_parameter_names = sorted(
        item["platform_parameter"] for item in mapping)
    parameter_domain_fingerprint = _digest({
        "domain_id": domain_id,
        "parameter_mapping": mapping,
        "config": config,
    })
    manifest = {
        "schema_version": 2,
        "kind": "official-openroad-autotuner-fairness-adapter",
        "domain_id": domain_id,
        "selected_parameter_names": selected_parameter_names,
        "parameter_domain_fingerprint": parameter_domain_fingerprint,
        "platform": calibrated_profile.get("platform"),
        "parameter_mapping": mapping,
        "excluded_from_official_search": excluded,
        "fixed_flow_environment": fixed_environment,
        "fixed_implementation_seed": int(or_seed),
        "frozen_constraints": list(calibrated_profile.get("frozen_constraints") or ()),
        "forbidden_constraint_tokens": list(FORBIDDEN_CONSTRAINT_TOKENS),
        "calibration_protocol": calibration.get("protocol"),
        "calibration_evaluation_count": calibration.get("evaluation_count"),
        "limitations": [
            "The upstream AutoTuner objective is scalar; trials are re-scored by the common paper evaluator.",
            "Upstream --work-dir is omitted because its metric reader ignores WORK_HOME in the pinned revision.",
            "Equal parameter domains do not imply algorithmic equivalence.",
            "Pinned AutoTuner quantized upper bounds are exclusive; the adapter encodes one extra step to preserve the platform's inclusive value set.",
        ],
    }
    manifest["config_sha256"] = _digest(config)
    manifest["manifest_fingerprint"] = _digest(manifest)
    return config, manifest


def write_fair_autotuner_bundle(
    output: str | Path, calibrated_profile: Mapping[str, Any], *,
    or_seed: int, env_names: Mapping[str, str], domain_id: str,
    supported_env_names: Iterable[str] | None = None,
) -> dict[str, Any]:
    destination = Path(output).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    config, manifest = build_fair_autotuner_config(
        calibrated_profile, or_seed=or_seed, env_names=env_names,
        domain_id=domain_id,
        supported_env_names=supported_env_names)
    config_path = destination / "autotuner.fair.json"
    manifest_path = destination / "fairness-manifest.json"
    _atomic_json(config_path, config)
    _atomic_json(manifest_path, {**manifest, "config_path": str(config_path)})
    return {**manifest, "config_path": str(config_path),
            "manifest_path": str(manifest_path)}


@dataclass(frozen=True)
class OfficialAutoTunerInvocation:
    python: str
    autotuner_root: str
    orfs_root: str
    design: str
    platform: str
    config_path: str
    experiment: str
    algorithm: str
    samples: int
    optimizer_seed: int
    jobs: int
    openroad_threads: int
    stop_stage: str = "finish"
    timeout_hours: float = 4.0
    resume: bool = False

    def validate(self) -> None:
        if self.algorithm not in SUPPORTED_ALGORITHMS:
            raise ValueError(f"unsupported official AutoTuner algorithm: {self.algorithm}")
        if not self.experiment or "/" in self.experiment or ".." in self.experiment:
            raise ValueError("experiment must be one safe namespace component")
        if not 1 <= self.samples <= 100_000:
            raise ValueError("samples must be between 1 and 100000")
        if not 1 <= self.jobs <= 64 or not 1 <= self.openroad_threads <= 64:
            raise ValueError("jobs and OpenROAD threads must be between 1 and 64")
        if self.jobs * self.openroad_threads > (os.cpu_count() or 1):
            raise ValueError("official AutoTuner request oversubscribes this host")
        if self.stop_stage not in {"floorplan", "place", "cts", "globalroute", "route", "finish"}:
            raise ValueError("invalid ORFS stop stage")
        for path in (self.python, self.autotuner_root, self.orfs_root, self.config_path):
            if not Path(path).expanduser().exists():
                raise FileNotFoundError(path)

    def command(self) -> tuple[str, ...]:
        self.validate()
        prefix = (
            # Do not resolve the venv's ``python`` symlink: CPython uses that
            # invocation path to discover pyvenv.cfg and site-packages.
            os.path.abspath(Path(self.python).expanduser()), "-m", "autotuner.distributed",
            "--design", self.design, "--platform", self.platform,
            "--config", str(Path(self.config_path).expanduser().resolve()),
            "--experiment", self.experiment,
            "--jobs", str(self.jobs), "--openroad_threads", str(self.openroad_threads),
            "--stop_stage", self.stop_stage, "--timeout", str(float(self.timeout_hours)),
            "tune",
        )
        return prefix + (("--resume",) if self.resume else ()) + (
            "--algorithm", self.algorithm, "--samples", str(self.samples),
            "--iterations", "1", "--resources_per_trial", str(self.openroad_threads),
            "--seed", str(self.optimizer_seed),
        )

    def working_directory(self) -> str:
        """Use FLOW_HOME so upstream's relative autotuner-best path resolves."""
        self.validate()
        return str(Path(self.orfs_root).expanduser().resolve() / "flow")

    def controlled_environment(self, *, openroad_wrapper: str,
                               yosys_wrapper: str,
                               fixed_flow_environment: Mapping[str, Any] = ()) -> dict[str, str]:
        self.validate()
        for path in (openroad_wrapper, yosys_wrapper):
            if not os.access(Path(path).expanduser(), os.X_OK):
                raise FileNotFoundError(f"toolchain wrapper is not executable: {path}")
        result = {
            # ORFS honours an inherited FLOW_HOME before deriving it from the
            # Makefile location.  Bind every path-valued flow variable to the
            # validated worktree so a developer shell cannot silently redirect
            # an official-control run to a mutable checkout.
            "FLOW_HOME": str(Path(self.orfs_root).expanduser().resolve() / "flow"),
            "DESIGN_HOME": str(
                Path(self.orfs_root).expanduser().resolve() / "flow/designs"),
            "PLATFORM_HOME": str(
                Path(self.orfs_root).expanduser().resolve() / "flow/platforms"),
            "UTILS_DIR": str(
                Path(self.orfs_root).expanduser().resolve() / "flow/util"),
            "SCRIPTS_DIR": str(
                Path(self.orfs_root).expanduser().resolve() / "flow/scripts"),
            "TEST_DIR": str(
                Path(self.orfs_root).expanduser().resolve() / "flow/test"),
            "OPENROAD_EXE": str(Path(openroad_wrapper).expanduser().resolve()),
            "YOSYS_EXE": str(Path(yosys_wrapper).expanduser().resolve()),
            "PYTHONHASHSEED": str(self.optimizer_seed),
        }
        for key, value in dict(fixed_flow_environment).items():
            if (not key or not key.replace("_", "").isalnum() or key.upper() != key
                    or any(token in key for token in FORBIDDEN_CONSTRAINT_TOKENS)):
                raise ValueError(f"unsafe fixed ORFS environment key: {key}")
            if isinstance(value, bool):
                value = int(value)
            if not isinstance(value, (str, int, float)):
                raise ValueError(f"fixed ORFS environment value must be scalar: {key}")
            result[key] = str(value)
        return result

    def manifest(self, *, environment: Mapping[str, str],
                 upstream_commit: str | None = None,
                 generated_design: Mapping[str, Any] | None = None) -> dict[str, Any]:
        value = {
            "schema_version": 1,
            "kind": "official-openroad-autotuner-invocation",
            "command": list(self.command()),
            "cwd": self.working_directory(),
            "environment": dict(sorted(environment.items())),
            "upstream_commit": upstream_commit,
            "artifact_root": str(
                Path(self.orfs_root).expanduser().resolve() / "flow/logs" /
                self.platform / self.design / f"{self.experiment}-tune"),
            "work_dir_omitted": True,
            "work_dir_reason": (
                "Pinned upstream computes metric paths under FLOW_HOME even when ORFS writes "
                "under WORK_HOME; unique experiment/FLOW_VARIANT namespaces isolate artifacts."
            ),
            "cwd_reason": (
                "Pinned upstream set_best_params resolves designs/<platform>/<design>/"
                "autotuner-best.json relative to cwd; FLOW_HOME is the matching root."
            ),
            "generated_design": dict(generated_design or {}),
            "native_design_substitution": generated_design is None,
            "resume_requested": self.resume,
        }
        return {**value, "fingerprint": _digest(value)}


def _atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)
