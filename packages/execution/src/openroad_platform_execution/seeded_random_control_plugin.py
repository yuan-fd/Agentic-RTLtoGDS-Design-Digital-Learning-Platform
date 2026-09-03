"""Typed task builder for the fixed-seed equal-budget Random control plugin.

This is evaluation infrastructure, not a replacement for an admitted external
optimiser.  It produces transparent, non-adaptive control proposals over the
same already-admitted ORFS-Agent transport domain so a GP/EI campaign can be
compared against a real equal-budget baseline.
"""

from __future__ import annotations

import hashlib
import json
import platform
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

from openroad_platform_contracts import PluginManifest, TaskSpec

from .orfs_parameters import validate_orfs_parameters


SEEDED_RANDOM_CONTROL_PLUGIN_ID = "seeded-random-control"
SEEDED_RANDOM_CONTROL_PLUGIN_VERSION = "1.0.0"
ORFS_AGENT_SHARED_PARAMETER_NAMES = (
    "core_utilization_pct", "tns_end_percent", "global_placement_padding",
    "detail_placement_padding", "enable_dpo", "place_density_lb_addon",
    "cts_cluster_size", "cts_cluster_diameter",
)


def _fingerprint(parameters: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        dict(sorted(parameters.items())), sort_keys=True, separators=(",", ":"), default=str,
    ).encode()).hexdigest()


def _canonical_domain(
    *, platform_name: str, search_parameter_names: Sequence[str],
    fixed_parameters: Mapping[str, Any], admissible_values: Mapping[str, Sequence[Any]],
) -> tuple[tuple[str, ...], dict[str, Any], dict[str, list[Any]]]:
    names = tuple(str(name) for name in search_parameter_names)
    if not names or len(set(names)) != len(names):
        raise ValueError("search_parameter_names must be non-empty and distinct")
    shared = set(ORFS_AGENT_SHARED_PARAMETER_NAMES)
    if set(names) - shared:
        raise ValueError("random control received unsupported ORFS-Agent parameter names")
    fixed = validate_orfs_parameters(dict(fixed_parameters), platform=platform_name)
    if set(names) & set(fixed) or set(names) | set(fixed) != shared:
        raise ValueError("random control domain must search or fix every shared parameter exactly once")
    if set(admissible_values) != set(names):
        raise ValueError("admissible_values must define every and only searched parameter")
    values: dict[str, list[Any]] = {}
    for name in names:
        raw = admissible_values[name]
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            raise ValueError(f"admissible values for {name} must be a sequence")
        normalized: list[Any] = []
        for value in raw:
            canonical = validate_orfs_parameters({name: value}, platform=platform_name)[name]
            if canonical not in normalized:
                normalized.append(canonical)
        if len(normalized) < 2:
            raise ValueError(f"random control needs at least two values for {name}")
        values[name] = normalized
    return names, fixed, values


def build_seeded_random_control_task(
    *, project_id: str, design_id: str, platform_name: str, objective: str,
    search_parameter_names: Sequence[str], fixed_parameters: Mapping[str, Any],
    admissible_values: Mapping[str, Sequence[Any]], excluded_parameters: Sequence[Mapping[str, Any]],
    n_suggestions: int, seed: int, timeout_seconds: int = 1800, task_id: str | None = None,
) -> TaskSpec:
    """Request a fixed-size, without-replacement Random-control batch.

    ``excluded_parameters`` covers baseline, warm-up, feasible and infeasible
    past coordinates alike.  It is therefore an execution budget guard, not a
    training dataset and cannot introduce adaptive QoR behaviour.
    """
    if not 1 <= int(n_suggestions) <= 64:
        raise ValueError("n_suggestions must be between 1 and 64")
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        raise ValueError("seed must be a non-negative integer")
    names, fixed, values = _canonical_domain(
        platform_name=platform_name, search_parameter_names=search_parameter_names,
        fixed_parameters=fixed_parameters, admissible_values=admissible_values,
    )
    excluded: list[str] = []
    for row in excluded_parameters:
        if not isinstance(row, Mapping):
            raise ValueError("excluded_parameters must contain parameter mappings")
        shared_row = {name: row[name] for name in ORFS_AGENT_SHARED_PARAMETER_NAMES if name in row}
        if set(shared_row) != set(ORFS_AGENT_SHARED_PARAMETER_NAMES):
            raise ValueError("excluded parameter vector lacks a shared ORFS-Agent field")
        canonical = validate_orfs_parameters(shared_row, platform=platform_name)
        excluded.append(_fingerprint(canonical))
    if len(set(excluded)) != len(excluded):
        excluded = list(dict.fromkeys(excluded))
    task = TaskSpec(
        task_id=task_id or f"seeded-random-control-{uuid.uuid4().hex}",
        project_id=project_id, design_id=design_id,
        plugin_id=SEEDED_RANDOM_CONTROL_PLUGIN_ID,
        inputs={
            "mode": "propose", "design": design_id, "platform": platform_name,
            "objective": objective, "search_parameter_names": list(names),
            "fixed_parameters": fixed, "admissible_values": values,
            "excluded_parameter_fingerprints": sorted(excluded),
            "n_suggestions": int(n_suggestions), "seed": seed,
        },
        timeout_seconds=timeout_seconds, max_attempts=1,
        expected_artifacts=("optimizer_candidates", "optimizer_input_manifest", "optimizer_trace"),
        labels={
            "optimizer_origin": "internal:fixed-seed-random-control",
            "algorithm_owner": "evaluation-protocol", "execution_owner": "platform-runtime",
        },
    )
    task.validate()
    return task


def seeded_random_control_plugin_manifest(
    *, python_executable: str | Path = sys.executable, default_timeout_seconds: int = 1800,
) -> PluginManifest:
    python = Path(python_executable).expanduser().absolute()
    if not python.is_file():
        raise FileNotFoundError(f"Python executable is missing: {python}")
    root = Path(__file__).resolve().parents[4]
    adapter = root / "integrations/seeded_random_control/seeded_random_control_adapter.py"
    if not adapter.is_file():
        raise FileNotFoundError("seeded Random control adapter is missing")
    manifest = PluginManifest(
        plugin_id=SEEDED_RANDOM_CONTROL_PLUGIN_ID,
        plugin_version=SEEDED_RANDOM_CONTROL_PLUGIN_VERSION,
        adapter_entry=(str(python), str(adapter)),
        capabilities=("optimizer.l2.control.random",),
        supported_arch=(platform.machine(),),
        input_schema={"type": "object", "required": [
            "mode", "design", "platform", "objective", "search_parameter_names",
            "fixed_parameters", "admissible_values", "n_suggestions", "seed",
        ]},
        output_schema={"type": "object", "required": ["status", "artifacts", "provenance"]},
        required_tools=("python3",), default_timeout_seconds=default_timeout_seconds,
        artifact_rules=(
            {"kind": "optimizer_candidates", "required": True},
            {"kind": "optimizer_input_manifest", "required": True},
            {"kind": "optimizer_trace", "required": True},
            {"kind": "log", "required": False},
        ),
        environment={"PYTHONDONTWRITEBYTECODE": "1", "PATH": f"{python.parent}:/usr/bin:/bin"},
    )
    manifest.validate()
    return manifest
