"""Task builder for the pinned external ORFS-Agent L2 adapter.

This module intentionally contains no search algorithm.  ORFS-Agent owns the
published optimiser; the platform owns the versioned task envelope and Runtime
execution boundary.
"""

from __future__ import annotations

import json
import itertools
import hashlib
import os
import platform
import random
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

from openroad_platform_contracts.platform import PluginManifest, TaskSpec
from .orfs_parameters import ORFS_PARAMETER_BY_NAME, validate_orfs_parameters


ORFS_AGENT_PLUGIN_ID = "orfs-agent"
ORFS_AGENT_PLUGIN_VERSION = "2025.1"
ORFS_AGENT_UPSTREAM_COMMIT = "730f1fa11f9c17c0aaac332412af2b2538f42e9b"
ORFS_AGENT_PAPER_ORFS_COMMIT = "ce8d36a7fef0ab9c47d183bcf078bce0f60f5a54"
ORFS_AGENT_SHARED_PARAMETER_NAMES = (
    "core_utilization_pct", "tns_end_percent", "global_placement_padding",
    "detail_placement_padding", "enable_dpo", "place_density_lb_addon",
    "cts_cluster_size", "cts_cluster_diameter",
)


def _validate_execution_source(source: Path, lock: Mapping[str, Any]) -> None:
    """Fail at composition time when a source-audit cache is used as code."""
    cache = (Path(__file__).resolve().parents[4] / str(lock["cache_path"])).resolve()
    if source == cache:
        raise ValueError("ORFS-Agent source-audit cache is not an executable checkout")
    if not source.is_dir():
        raise FileNotFoundError(f"ORFS-Agent source is missing: {source}")
    git = ("git", "-C", str(source))
    actual = subprocess.check_output((*git, "rev-parse", "HEAD"), text=True).strip()
    if actual != lock.get("commit"):
        raise ValueError("ORFS-Agent execution checkout does not match the source lock")
    if subprocess.run((*git, "symbolic-ref", "-q", "HEAD"), stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL, check=False).returncode == 0:
        raise ValueError("ORFS-Agent execution checkout must be detached")
    if subprocess.check_output((*git, "status", "--porcelain", "--untracked-files=all"), text=True):
        raise ValueError("ORFS-Agent execution checkout must be clean, including untracked files")
    license_path = source / "LICENSE"
    if (not license_path.is_file()
            or "BSD 3-Clause License" not in license_path.read_text(encoding="utf-8")):
        raise ValueError("ORFS-Agent BSD-3-Clause execution license check failed")


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


def _validate_paper_execution_source(source: Path) -> None:
    if not (source / "flow/Makefile").is_file():
        raise FileNotFoundError("paper ORFS flow is missing")
    git = ("git", "-C", str(source))
    actual = subprocess.check_output((*git, "rev-parse", "HEAD"), text=True).strip()
    if actual != ORFS_AGENT_PAPER_ORFS_COMMIT:
        raise ValueError("paper ORFS checkout does not match the admitted commit")
    if subprocess.run((*git, "symbolic-ref", "-q", "HEAD"), stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL, check=False).returncode == 0:
        raise ValueError("paper ORFS execution checkout must be detached")
    if subprocess.check_output((*git, "status", "--porcelain", "--untracked-files=all"), text=True):
        raise ValueError("paper ORFS execution checkout must be clean, including submodule state")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_sha256(root: Path, *, ignored_names: frozenset[str] = frozenset()) -> str:
    if not root.is_dir():
        raise FileNotFoundError(f"tool data directory is missing: {root}")
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] in ignored_names:
            continue
        if path.is_symlink():
            digest.update(f"L\0{relative}\0{os.readlink(path)}\n".encode())
        elif path.is_file():
            digest.update(f"F\0{relative}\0{path.stat().st_size}\0".encode())
            digest.update(_file_sha256(path).encode())
            digest.update(b"\n")
    return digest.hexdigest()


def _receipt_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


def _git_object(root: Path, relative: str) -> str:
    return subprocess.check_output(
        ("git", "-C", str(root), "rev-parse", f"HEAD:{relative}"), text=True,
    ).strip()


def _paper_receipts(
    *, source: Path, paper_root: Path, openroad: Path, yosys: Path,
    runtime_environment: Mapping[str, str],
) -> dict[str, Any]:
    yosys_share = yosys.parent.parent / "share"
    yosys_datdir = yosys_share / "yosys"
    if not yosys_datdir.is_dir() or yosys_datdir.resolve() != yosys_share.resolve():
        raise ValueError("Yosys compiled datdir share/yosys does not resolve to installed data")
    toolchain = {
        "schema_version": 1, "kind": "orfs-agent-paper-toolchain",
        "orfs_agent_commit": ORFS_AGENT_UPSTREAM_COMMIT,
        "paper_orfs_commit": ORFS_AGENT_PAPER_ORFS_COMMIT,
        "openroad_sha256": _file_sha256(openroad),
        "yosys_sha256": _file_sha256(yosys),
        "yosys_datdir_sha256": _tree_sha256(
            yosys_share, ignored_names=frozenset({"yosys"})),
        "yosys_datdir_layout": "share/yosys resolves to installed share root",
        "runtime_environment": dict(sorted(runtime_environment.items())),
        "architecture": platform.machine(),
    }
    configs = source / "AutoTuner-integration/AutoTuner/autotune_configs"
    sdc_names = {"aes": "aes_cipher_top.sdc", "ibex": "ibex_core.sdc",
                 "jpeg": "jpeg_encoder.sdc"}
    inputs: dict[str, Any] = {}
    for design in ("aes", "ibex", "jpeg"):
        design_tree = _git_object(paper_root, f"flow/designs/src/{design}")
        for platform_name in ("asap7", "sky130hd"):
            design_receipt = {
                "schema_version": 1, "kind": "orfs-agent-paper-design-bundle",
                "design": design, "platform": platform_name,
                "paper_orfs_commit": ORFS_AGENT_PAPER_ORFS_COMMIT,
                "paper_design_tree_git_oid": design_tree,
                "autotuner_config_sha256": _file_sha256(configs / f"{design}_{platform_name}.mk"),
                "autotuner_sdc_sha256": _file_sha256(configs / sdc_names[design]),
                "autotuner_fastroute_sha256": _file_sha256(configs / f"fastroute_{platform_name}.tcl"),
            }
            pdk_receipt = {
                "schema_version": 1, "kind": "orfs-agent-paper-pdk-bundle",
                "platform": platform_name,
                "paper_orfs_commit": ORFS_AGENT_PAPER_ORFS_COMMIT,
                "paper_platform_tree_git_oid": _git_object(
                    paper_root, f"flow/platforms/{platform_name}"),
            }
            inputs[f"{platform_name}/{design}"] = {
                "design": design_receipt,
                "design_bundle_sha256": _receipt_sha256(design_receipt),
                "pdk": pdk_receipt,
                "pdk_bundle_sha256": _receipt_sha256(pdk_receipt),
            }
    return {"toolchain": toolchain,
            "toolchain_receipt_sha256": _receipt_sha256(toolchain),
            "inputs": inputs}


def orfs_agent_full_protocol_receipts(
    *, source_root: str | Path, paper_orfs_root: str | Path,
    openroad_bin: str | Path, yosys_bin: str | Path,
    design: str, platform_name: str,
    paper_runtime_environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return hash-bound protocol identities for one admitted full campaign."""
    source = Path(source_root).expanduser().resolve()
    paper_root = Path(paper_orfs_root).expanduser().resolve()
    openroad = Path(openroad_bin).expanduser().resolve()
    yosys = Path(yosys_bin).expanduser().resolve()
    lock_path = Path(__file__).resolve().parents[4] / "integrations/orfs_agent/source.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    _validate_execution_source(source, lock)
    _validate_paper_execution_source(paper_root)
    for executable in (openroad, yosys):
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise FileNotFoundError(f"paper tool executable is missing: {executable}")
    runtime_environment = dict(paper_runtime_environment or {})
    if any(key not in {"LD_LIBRARY_PATH", "LIBRARY_PATH", "TCLLIBPATH"}
           or not isinstance(value, str) for key, value in runtime_environment.items()):
        raise ValueError("paper runtime environment contains an unsupported entry")
    receipts = _paper_receipts(
        source=source, paper_root=paper_root, openroad=openroad, yosys=yosys,
        runtime_environment=runtime_environment,
    )
    try:
        selected = receipts["inputs"][f"{platform_name}/{design}"]
    except KeyError as exc:
        raise ValueError("unsupported full ORFS-Agent design/platform") from exc
    return {**selected,
            "toolchain": receipts["toolchain"],
            "toolchain_receipt_sha256": receipts["toolchain_receipt_sha256"]}


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
    paper_orfs_root: str | Path | None = None,
    openroad_bin: str | Path | None = None,
    yosys_bin: str | Path | None = None,
    paper_runtime_environment: Mapping[str, str] | None = None,
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
    _validate_execution_source(source, lock)
    adapter = Path(__file__).resolve().parents[4] / "integrations/orfs_agent/orfs_agent_adapter.py"
    environment = {"ORFS_AGENT_SOURCE": str(source),
                   "ORFS_AGENT_EXPECTED_COMMIT": ORFS_AGENT_UPSTREAM_COMMIT,
                   "PYTHONDONTWRITEBYTECODE": "1",
                   "PATH": f"{python.parent}:/usr/bin:/bin"}
    paper_values = (paper_orfs_root, openroad_bin, yosys_bin)
    if any(value is not None for value in paper_values):
        if not all(value is not None for value in paper_values):
            raise ValueError("paper ORFS root, OpenROAD, and Yosys must be configured together")
        paper_root = Path(str(paper_orfs_root)).expanduser().resolve()
        openroad = Path(str(openroad_bin)).expanduser().resolve()
        yosys = Path(str(yosys_bin)).expanduser().resolve()
        _validate_paper_execution_source(paper_root)
        for name, executable in (("OpenROAD", openroad), ("Yosys", yosys)):
            if not executable.is_file() or not os.access(executable, os.X_OK):
                raise FileNotFoundError(f"paper {name} executable is missing: {executable}")
        environment.update({
            "ORFS_AGENT_PAPER_ORFS_ROOT": str(paper_root),
            "ORFS_AGENT_PAPER_ORFS_COMMIT": ORFS_AGENT_PAPER_ORFS_COMMIT,
            "OPENROAD_BIN": str(openroad), "YOSYS_BIN": str(yosys),
            "PATH": f"{openroad.parent}:{yosys.parent}:{python.parent}:/usr/bin:/bin",
        })
        for key, value in dict(paper_runtime_environment or {}).items():
            if key not in {"LD_LIBRARY_PATH", "LIBRARY_PATH", "TCLLIBPATH"} or not isinstance(value, str):
                raise ValueError(f"unsupported paper toolchain environment: {key}")
            environment[key] = value
        receipts = _paper_receipts(
            source=source, paper_root=paper_root, openroad=openroad, yosys=yosys,
            runtime_environment=dict(paper_runtime_environment or {}),
        )
        environment["ORFS_AGENT_PAPER_RECEIPTS_JSON"] = json.dumps(
            receipts, sort_keys=True, separators=(",", ":"),
        )
    elif paper_runtime_environment:
        raise ValueError("paper runtime environment requires the complete paper toolchain")
    codex = _managed_codex_executable()
    if codex:
        environment["ORFS_AGENT_CODEX_EXECUTABLE"] = codex
        # Codex is a node launcher; retain its containing directory rather
        # than relying on an interactive shell profile in an adapter process.
        node = shutil.which("node")
        if node:
            environment["PATH"] = f"{Path(node).parent}:{environment['PATH']}"
    capabilities = ["optimizer.l2.propose", "optimizer.l2.dataset-bridge",
                    "optimizer.l2.upstream-full-12d"]
    if all(value is not None for value in paper_values):
        capabilities.append("optimizer.l2.upstream-full-candidate")
    manifest = PluginManifest(
        plugin_id=ORFS_AGENT_PLUGIN_ID, plugin_version=ORFS_AGENT_PLUGIN_VERSION,
        adapter_entry=(str(python), str(adapter)),
        capabilities=tuple(capabilities),
        supported_arch=(platform.machine(),),
        input_schema={"type": "object", "required": ["mode", "design", "platform", "parameter_domain"]},
        output_schema={"type": "object", "required": ["status", "artifacts", "provenance"]},
        required_tools=(("git", "python3", "make", "openroad", "yosys")
                        if all(value is not None for value in paper_values)
                        else ("git", "python3")),
        artifact_rules=(
            # Required kinds are mode-specific and therefore live on TaskSpec.
            # A manifest-wide requirement would force the full-policy mode to
            # fabricate a dataset-bridge manifest (or vice versa).
            {"kind": "optimizer_dataset", "required": False},
            {"kind": "optimizer_input_manifest", "required": False},
            {"kind": "upstream_source_lock", "required": False},
            {"kind": "optimizer_candidates", "required": False},
            {"kind": "optimizer_trace", "required": False},
            {"kind": "runtime_protocol_receipt", "required": False},
            {"kind": "mapped_orfs_config", "required": False},
            {"kind": "report", "required": False}, {"kind": "log", "required": False},
            {"kind": "odb", "required": False}, {"kind": "def", "required": False},
            {"kind": "netlist", "required": False}, {"kind": "sdc", "required": False},
            {"kind": "spef", "required": False},
        ),
        environment=environment,
    )
    manifest.validate()
    return manifest
