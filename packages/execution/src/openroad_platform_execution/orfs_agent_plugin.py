"""Task builder for the pinned external ORFS-Agent L2 adapter.

This module intentionally contains no search algorithm.  ORFS-Agent owns the
published optimiser; the platform owns the versioned task envelope and Runtime
execution boundary.
"""

from __future__ import annotations

import json
import itertools
import os
import platform
import random
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

from openroad_platform_contracts.platform import PluginManifest, TaskSpec
from .orfs_parameters import ORFS_PARAMETER_BY_NAME, validate_orfs_parameters


ORFS_AGENT_PLUGIN_ID = "orfs-agent"
ORFS_AGENT_PLUGIN_VERSION = "2025.1"
ORFS_AGENT_UPSTREAM_COMMIT = "730f1fa11f9c17c0aaac332412af2b2538f42e9b"
ORFS_AGENT_SHARED_PARAMETER_NAMES = (
    "core_utilization_pct", "tns_end_percent", "global_placement_padding",
    "detail_placement_padding", "enable_dpo", "place_density_lb_addon",
    "cts_cluster_size", "cts_cluster_diameter",
)


def _managed_codex_executable() -> str | None:
    """Locate the platform-managed Codex binary without relying on a login shell.

    Runtime adapters receive a deliberately minimal ``PATH``.  A user-systemd
    service also does not source interactive shell startup files, so resolving
    ``codex`` only with :func:`shutil.which` at manifest construction can make
    a later native-agent invocation fail even though the platform installation
    is present.  This returns an absolute executable path and never accepts a
    user-supplied model/provider setting.
    """
    configured = os.environ.get("OPENROAD_PLATFORM_CODEX_EXECUTABLE")
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured).expanduser())
    discovered = shutil.which("codex")
    if discovered:
        candidates.append(Path(discovered))
    nvm_root = Path.home() / ".nvm" / "versions" / "node"
    if nvm_root.is_dir():
        candidates.extend(sorted(nvm_root.glob("*/bin/codex"), reverse=True))
    for candidate in candidates:
        # Verify the executable's resolved target, but retain its lexical
        # launcher path. NVM's ``bin/codex`` is a symlink whose adjacent
        # ``bin/node`` is required by the launcher's ``env node`` shebang.
        # Returning the resolved JavaScript target loses that boundary.
        launcher = candidate.expanduser().absolute()
        resolved = launcher.resolve()
        if resolved.is_file() and os.access(resolved, os.X_OK):
            return str(launcher)
    return None


def build_orfs_agent_initial_warmup_recipes(
    *, platform_name: str, count: int, seed: int,
    admissible_values: Mapping[str, Sequence[Any]] | None = None,
    fixed_parameters: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Materialize a frozen, upstream-derived initial DOE receipt.

    This is *not* a second optimiser.  It is the typed equivalent of the
    pinned ORFS-Agent ``OptimizationWorkflow.generate_initial_parameters``
    initializer: independently draw every active numeric/binary knob before
    the upstream GP/EI is asked to fit observations.  The platform narrows
    only the transport intersection (notably ``LB_ADDON <= .50``) and projects
    ``DP_PAD <= GP_PAD`` so every recipe is executable under its protected
    ORFS contract.  A recorded seed makes the otherwise-random upstream
    initialization reproducible and auditable.
    """
    if not 8 <= int(count) <= 512:
        raise ValueError("ORFS-Agent warm-up count must be between 8 and 512")
    if int(seed) < 0:
        raise ValueError("ORFS-Agent warm-up seed must be non-negative")
    rng = random.Random(int(seed))
    if (admissible_values is None) != (fixed_parameters is None):
        raise ValueError("target-domain warm-up needs both admissible_values and fixed_parameters")
    if admissible_values is not None:
        values = dict(admissible_values)
        fixed = validate_orfs_parameters(dict(fixed_parameters or {}), platform=platform_name)
        names = set(values)
        shared = set(ORFS_AGENT_SHARED_PARAMETER_NAMES)
        if not names or names & set(fixed) or names | set(fixed) != shared:
            raise ValueError("target-domain warm-up must partition the ORFS-Agent shared domain")
        normalized: dict[str, list[Any]] = {}
        for name in sorted(names):
            raw_values = values[name]
            if not isinstance(raw_values, Sequence) or isinstance(raw_values, (str, bytes)):
                raise ValueError(f"target-domain values for {name} must be a sequence")
            candidates = []
            for value in raw_values:
                canonical = validate_orfs_parameters({name: value}, platform=platform_name)[name]
                if canonical not in candidates:
                    candidates.append(canonical)
            if len(candidates) < 2:
                raise ValueError(f"target-domain search parameter {name} needs at least two values")
            normalized[name] = candidates
        configurations = []
        for combination in itertools.product(*(normalized[name] for name in sorted(normalized))):
            candidate = {**fixed, **dict(zip(sorted(normalized), combination))}
            try:
                configurations.append(validate_orfs_parameters(candidate, platform=platform_name))
            except ValueError:
                # Cross-parameter legality is a hard Runtime contract.  An
                # impossible Cartesian point is not a warm-up failure and is
                # never sent to ORFS merely to consume a budget slot.
                continue
        if len(configurations) < int(count):
            raise ValueError(
                f"target-domain has only {len(configurations)} legal distinct warm-up configurations; "
                f"protocol requires {count}")
        rng.shuffle(configurations)
        return [{
            "recipe_id": f"orfs-agent-target-domain-{index:03d}",
            "parameters": parameters,
            "origin": {
                "upstream": "OptimizationWorkflow.generate_initial_parameters",
                "upstream_commit": ORFS_AGENT_UPSTREAM_COMMIT,
                "sampling": "seeded-permutation-of-admitted-discrete-target-domain",
                "seed": int(seed),
                "domain_kind": "target-feasibility-subtractive",
            },
        } for index, parameters in enumerate(configurations[:int(count)])]
    recipes: list[dict[str, Any]] = []
    fingerprints: set[str] = set()
    # The ranges are the exact common/upstream domain seen by the native
    # workbench, after the platform's documented physical-parameter bounds.
    # Keep this map beside the adapter rather than leaking it into Runtime or
    # a general-purpose local DSE implementation.
    utilization_lower = {"asap7": 30, "sky130hd": 20}.get(platform_name, 20)
    while len(recipes) < int(count):
        global_padding = rng.randint(0, 3)
        parameters = validate_orfs_parameters({
            "core_utilization_pct": rng.randint(utilization_lower, 69),
            "tns_end_percent": rng.randint(0, 100),
            "global_placement_padding": global_padding,
            "detail_placement_padding": rng.randint(0, global_padding),
            "enable_dpo": rng.randint(0, 1),
            "place_density_lb_addon": round(rng.uniform(0.0, 0.50), 4),
            "cts_cluster_size": rng.randint(10, 40),
            "cts_cluster_diameter": rng.randint(80, 120),
        }, platform=platform_name)
        fingerprint = json.dumps(parameters, sort_keys=True, separators=(",", ":"))
        if fingerprint in fingerprints:
            continue
        fingerprints.add(fingerprint)
        recipes.append({
            "recipe_id": f"orfs-agent-initial-{len(recipes):03d}",
            "parameters": parameters,
            "origin": {
                "upstream": "OptimizationWorkflow.generate_initial_parameters",
                "upstream_commit": ORFS_AGENT_UPSTREAM_COMMIT,
                "sampling": "independent_uniform_per_active_parameter",
                "seed": int(seed),
            },
        })
    return recipes


def build_orfs_agent_dataset_task(
    *, project_id: str, design_id: str, platform_name: str, objective: str,
    observations: Sequence[Mapping[str, Any]], timeout_seconds: int = 1800,
    task_id: str | None = None,
    search_parameter_names: Sequence[str] | None = None,
    fixed_parameters: Mapping[str, Any] | None = None,
    admissible_values: Mapping[str, Sequence[Any]] | None = None,
) -> TaskSpec:
    """Build the first executable integration step: upstream data materialization.

    This must receive full observation objects rather than a prompt summary.
    The adapter preserves source observation/artifact references in the flat
    upstream-compatible rows so an ORFS-Agent suggestion remains traceable.
    """
    if not observations:
        raise ValueError("ORFS-Agent needs at least one Runtime observation")
    if not all(isinstance(item, Mapping) for item in observations):
        raise ValueError("ORFS-Agent observations must be objects")
    search_names = (ORFS_AGENT_SHARED_PARAMETER_NAMES if search_parameter_names is None
                    else tuple(str(name) for name in search_parameter_names))
    if not search_names or len(set(search_names)) != len(search_names):
        raise ValueError("ORFS-Agent search parameters must be non-empty and distinct")
    unknown = sorted(set(search_names) - set(ORFS_PARAMETER_BY_NAME))
    if unknown:
        raise ValueError(f"Unknown ORFS-Agent search parameters: {', '.join(unknown)}")
    fixed = validate_orfs_parameters(dict(fixed_parameters or {}), platform=platform_name)
    overlap = sorted(set(search_names) & set(fixed))
    if overlap:
        raise ValueError("ORFS-Agent search and fixed parameters overlap: " + ", ".join(overlap))
    # The adapter's supported shared domain is deliberately narrower than the
    # entire ORFS parameter registry.  A campaign must make this explicit
    # instead of sending a partial candidate that Runtime would later expand
    # ambiguously.
    shared = set(ORFS_AGENT_SHARED_PARAMETER_NAMES)
    unsupported = sorted(set(search_names) - shared)
    if unsupported:
        raise ValueError("ORFS-Agent shared domain does not support: " + ", ".join(unsupported))
    if set(search_names) | set(fixed) != shared:
        missing = sorted(shared - (set(search_names) | set(fixed)))
        raise ValueError("ORFS-Agent domain must search or fix every shared parameter: " + ", ".join(missing))
    canonical_values: dict[str, list[Any]] | None = None
    if admissible_values is not None:
        values = dict(admissible_values)
        if set(values) != set(search_names):
            raise ValueError("ORFS-Agent admissible_values must define every and only search parameter")
        canonical_values = {}
        for name in search_names:
            raw_values = values[name]
            if not isinstance(raw_values, Sequence) or isinstance(raw_values, (str, bytes)):
                raise ValueError(f"ORFS-Agent admissible values for {name} must be a sequence")
            normalized = []
            for value in raw_values:
                canonical = validate_orfs_parameters({name: value}, platform=platform_name)[name]
                if canonical not in normalized:
                    normalized.append(canonical)
            if len(normalized) < 2:
                raise ValueError(f"ORFS-Agent search parameter {name} needs at least two admissible values")
            canonical_values[name] = normalized
    task = TaskSpec(
        task_id=task_id or f"orfs-agent-{uuid.uuid4().hex}",
        project_id=project_id, design_id=design_id, plugin_id=ORFS_AGENT_PLUGIN_ID,
        inputs={"mode": "materialize_dataset", "design": design_id,
                "platform": platform_name, "objective": objective,
                "observations": [dict(item) for item in observations],
                "search_parameter_names": list(search_names),
                "fixed_parameters": fixed,
                **({"admissible_values": canonical_values} if canonical_values is not None else {})},
        timeout_seconds=timeout_seconds, max_attempts=1,
        expected_artifacts=("optimizer_dataset", "optimizer_input_manifest", "upstream_source_lock"),
        labels={"optimizer_origin": "external:ORFS-Agent",
                "algorithm_owner": "upstream", "execution_owner": "platform-runtime"},
    )
    task.validate()
    return task


def build_orfs_agent_native_task(
    *, project_id: str, design_id: str, platform_name: str, objective: str,
    observations: Sequence[Mapping[str, Any]], n_suggestions: int,
    optimizer_seed: int = 1, timeout_seconds: int = 1800,
    task_id: str | None = None,
    search_parameter_names: Sequence[str] | None = None,
    fixed_parameters: Mapping[str, Any] | None = None,
    admissible_values: Mapping[str, Sequence[Any]] | None = None,
) -> TaskSpec:
    """Request the pinned upstream GP/EI entrypoint through the same bridge.

    This is deliberately a TaskSpec builder, not a local optimizer.  It adds
    only bounded invocation settings to the dataset task; the adapter calls
    the upstream workbench and records its raw proposal trace.
    """
    if not 1 <= int(n_suggestions) <= 64:
        raise ValueError("n_suggestions must be between 1 and 64")
    if int(optimizer_seed) < 0:
        raise ValueError("optimizer_seed must be non-negative")
    dataset_task = build_orfs_agent_dataset_task(
        project_id=project_id, design_id=design_id, platform_name=platform_name,
        objective=objective, observations=observations,
        timeout_seconds=timeout_seconds, task_id=task_id,
        search_parameter_names=search_parameter_names, fixed_parameters=fixed_parameters,
        admissible_values=admissible_values,
    )
    return TaskSpec.from_dict({
        **dataset_task.to_dict(),
        "inputs": {
            **dataset_task.inputs, "mode": "native_agent",
            "n_suggestions": int(n_suggestions),
            "optimizer_seed": int(optimizer_seed),
        },
        "expected_artifacts": (*dataset_task.expected_artifacts,
                               "optimizer_candidates", "optimizer_trace"),
    })


def orfs_agent_plugin_manifest(
    source_root: str | Path, *, python_executable: str | Path = sys.executable,
    default_timeout_seconds: int = 1800,
) -> PluginManifest:
    source = Path(source_root).expanduser().resolve()
    python = Path(python_executable).expanduser().absolute()
    if not python.is_file():
        raise FileNotFoundError(f"Python executable is missing: {python}")
    if not (source / "AutoTuner-integration/ORFS-with-AutoTuner/analyst_agent_workbench.py").is_file():
        raise FileNotFoundError("pinned ORFS-Agent analyst source is missing")
    lock_path = Path(__file__).resolve().parents[4] / "integrations/orfs_agent/source.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if lock.get("commit") != ORFS_AGENT_UPSTREAM_COMMIT:
        raise ValueError("ORFS-Agent source lock does not match the admitted upstream commit")
    adapter = Path(__file__).resolve().parents[4] / "integrations/orfs_agent/orfs_agent_adapter.py"
    environment = {"ORFS_AGENT_SOURCE": str(source),
                   "ORFS_AGENT_EXPECTED_COMMIT": ORFS_AGENT_UPSTREAM_COMMIT,
                   "PYTHONDONTWRITEBYTECODE": "1",
                   "PATH": f"{python.parent}:/usr/bin:/bin"}
    codex = _managed_codex_executable()
    if codex:
        environment["ORFS_AGENT_CODEX_EXECUTABLE"] = codex
        # Codex is a node launcher; retain its containing directory rather
        # than relying on an interactive shell profile in an adapter process.
        node = shutil.which("node")
        if node:
            environment["PATH"] = f"{Path(node).parent}:{python.parent}:/usr/bin:/bin"
    manifest = PluginManifest(
        plugin_id=ORFS_AGENT_PLUGIN_ID, plugin_version=ORFS_AGENT_PLUGIN_VERSION,
        adapter_entry=(str(python), str(adapter)),
        capabilities=("optimizer.l2.propose", "optimizer.l2.dataset-bridge"),
        supported_arch=(platform.machine(),),
        input_schema={"type": "object", "required": ["mode", "design", "platform", "objective", "observations"]},
        output_schema={"type": "object", "required": ["status", "artifacts", "provenance"]},
        required_tools=("git", "python3"), default_timeout_seconds=default_timeout_seconds,
        artifact_rules=(
            {"kind": "optimizer_dataset", "required": True},
            {"kind": "optimizer_input_manifest", "required": True},
            {"kind": "upstream_source_lock", "required": True},
            {"kind": "optimizer_candidates", "required": False},
            {"kind": "optimizer_trace", "required": False},
            {"kind": "report", "required": False}, {"kind": "log", "required": False},
        ),
        environment=environment,
    )
    manifest.validate()
    return manifest
