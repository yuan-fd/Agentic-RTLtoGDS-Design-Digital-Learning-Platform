"""Immutable generated-design adapters for tools that require ORFS design discovery.

The platform runner accepts an arbitrary config path and DESIGN_HOME.  The
upstream AutoTuner does not: it hard-codes ``flow/designs/<pdk>/<design>``.
This module bridges that discovery convention without changing the upstream
optimizer and without substituting an ORFS-native benchmark for the platform
design under test.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from .orfs_parameters import orfs_parameter_config_lines, validate_orfs_parameters
from .orfs_design_options import (
    orfs_design_option_config_lines, validate_orfs_design_options,
)

if TYPE_CHECKING:
    from .orfs_reference_designs import ORFSReferenceDesign


SAFE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,95}$")
IDENTITY_KEYS_V2 = (
    "schema_version", "kind", "platform", "top", "rtl_sources",
    "rtl_include_files", "rtl_include_dirs", "synth_hdl_frontend",
    "autotuner_initial_points", "sdc_sha256", "sdc_size_bytes",
    "clock_period_ns", "core_utilization_pct", "place_density", "or_seed",
    "flow_parameters", "design_options", "source_identity",
)
IDENTITY_KEYS_V3 = (*IDENTITY_KEYS_V2, "configuration_policy_version")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()).hexdigest()


def install_generated_design_adapter(
    *,
    orfs_root: str | Path,
    platform: str,
    top: str,
    rtl_files: Mapping[str, str | Path],
    sdc_path: str | Path,
    clock_period_ns: float,
    core_utilization_pct: float,
    place_density: float,
    or_seed: int,
    flow_parameters: Mapping[str, Any],
    source_identity: Mapping[str, Any],
    rtl_include_dirs: Mapping[str, str | Path] | None = None,
    synth_hdl_frontend: str | None = None,
    autotuner_initial_points: Sequence[Mapping[str, Any]] = (),
    design_options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Install one content-addressed ORFS design namespace.

    ``rtl_files`` keys are stable POSIX-style relative names.  Values identify
    the exact source bytes used by the platform evaluator.  Existing adapters
    are reusable only when their immutable manifest is byte-for-byte equal.
    """
    root = Path(orfs_root).expanduser().resolve()
    flow_home = root / "flow"
    if not (flow_home / "Makefile").is_file():
        raise FileNotFoundError(f"ORFS flow Makefile not found: {flow_home / 'Makefile'}")
    if not SAFE_NAME.fullmatch(platform) or not SAFE_NAME.fullmatch(top):
        raise ValueError("platform and top must be safe Verilog-style names")
    if not rtl_files:
        raise ValueError("at least one RTL source is required")
    if not 1 <= int(or_seed) <= 2**31 - 1:
        raise ValueError("OR_SEED must be a positive 32-bit integer")

    sources: list[dict[str, Any]] = []
    resolved: list[tuple[str, Path]] = []
    for relative, raw_path in rtl_files.items():
        if (not relative or relative.startswith(("/", "../")) or ".." in Path(relative).parts
                or Path(relative).suffix.lower() not in {".v", ".sv", ".vh", ".svh"}):
            raise ValueError(f"unsafe or unsupported RTL relative path: {relative}")
        source = Path(raw_path).expanduser().resolve()
        if not source.is_file() or source.stat().st_size == 0:
            raise FileNotFoundError(source)
        resolved.append((relative, source))
        sources.append({
            "relative_path": relative,
            "sha256": _sha256(source),
            "size_bytes": source.stat().st_size,
        })
    sdc = Path(sdc_path).expanduser().resolve()
    if not sdc.is_file() or sdc.stat().st_size == 0:
        raise FileNotFoundError(sdc)
    parameters = validate_orfs_parameters(dict(flow_parameters), platform=platform)
    recipe_options = validate_orfs_design_options(design_options)
    initial_points = [dict(sorted(point.items())) for point in autotuner_initial_points]
    for point in initial_points:
        if not point or any(not key or key.upper() != key for key in point):
            raise ValueError("AutoTuner initial points must use non-empty uppercase environment keys")
        if any(not isinstance(value, (int, float, str, bool)) for value in point.values()):
            raise ValueError("AutoTuner initial point values must be scalar")
    if synth_hdl_frontend not in {None, "yosys", "slang"}:
        raise ValueError("synth_hdl_frontend must be yosys, slang, or null")
    include_sources: list[tuple[str, Path]] = []
    include_files: list[dict[str, Any]] = []
    for relative_dir, raw_dir in (rtl_include_dirs or {}).items():
        if (not relative_dir or relative_dir.startswith(("/", "../"))
                or ".." in Path(relative_dir).parts):
            raise ValueError(f"unsafe RTL include relative directory: {relative_dir}")
        directory = Path(raw_dir).expanduser().resolve()
        if not directory.is_dir():
            raise FileNotFoundError(directory)
        for header in sorted(directory.rglob("*")):
            if header.is_file() and header.suffix.lower() in {".v", ".sv", ".vh", ".svh"}:
                relative = str(Path(relative_dir) / header.relative_to(directory))
                include_sources.append((relative, header))
                include_files.append({
                    "relative_path": relative, "sha256": _sha256(header),
                    "size_bytes": header.stat().st_size,
                })
    identity = {
        "schema_version": 3,
        "kind": "orfs-generated-design-identity",
        "configuration_policy_version": "exclusive-placement-density-v1",
        "platform": platform,
        "top": top,
        "rtl_sources": sources,
        "rtl_include_files": include_files,
        "rtl_include_dirs": list((rtl_include_dirs or {}).keys()),
        "synth_hdl_frontend": synth_hdl_frontend,
        "autotuner_initial_points": initial_points,
        "sdc_sha256": _sha256(sdc),
        "sdc_size_bytes": sdc.stat().st_size,
        "clock_period_ns": float(clock_period_ns),
        "core_utilization_pct": float(core_utilization_pct),
        "place_density": float(place_density),
        "or_seed": int(or_seed),
        "flow_parameters": parameters,
        "design_options": recipe_options,
        "source_identity": dict(source_identity),
    }
    identity_sha = _canonical_digest(identity)
    namespace = f"opv2_{top[:40]}_{identity_sha[:16]}"
    destination = flow_home / "designs" / platform / namespace
    copied_paths = [destination / "src" / relative for relative, _ in resolved]
    copied_sdc = destination / "constraint.sdc"
    config_lines = [
        f"export DESIGN_NAME = {top}",
        f"export DESIGN_NICKNAME = {namespace}",
        f"export PLATFORM = {platform}",
        "export VERILOG_FILES = " + " ".join(str(path) for path in copied_paths),
        f"export SDC_FILE = {copied_sdc}",
        f"export CLOCK_PERIOD = {float(clock_period_ns):g}",
        f"export CORE_UTILIZATION = {float(core_utilization_pct):g}",
        f"export OR_SEED = {int(or_seed)}",
    ]
    # Exactly one placement-density policy reaches ORFS.  When the lower-bound
    # addon is active, a simultaneous direct PLACE_DENSITY assignment is dead
    # configuration and must not appear in reproducibility evidence.
    if "place_density_lb_addon" not in parameters:
        config_lines.append(f"export PLACE_DENSITY = {float(place_density):g}")
    if rtl_include_dirs:
        config_lines.append("export VERILOG_INCLUDE_DIRS = " + " ".join(
            str(destination / "src" / relative) for relative in rtl_include_dirs))
    if synth_hdl_frontend:
        config_lines.append(f"export SYNTH_HDL_FRONTEND = {synth_hdl_frontend}")
    config_lines.extend(orfs_design_option_config_lines(recipe_options))
    extra = {name: value for name, value in parameters.items()
             if name not in {"core_utilization_pct", "place_density"}}
    config_lines.extend(orfs_parameter_config_lines(extra, platform=platform))
    config_text = "\n".join(config_lines) + "\n"
    initial_points_text = (json.dumps(initial_points, indent=2, sort_keys=True) + "\n"
                           if initial_points else None)
    manifest = {
        **identity,
        "identity_sha256": identity_sha,
        "namespace": namespace,
        "config_path": str(destination / "config.mk"),
        "adapter_root": str(destination),
        "config_sha256": hashlib.sha256(config_text.encode()).hexdigest(),
        "autotuner_initial_points_sha256": (
            hashlib.sha256(initial_points_text.encode()).hexdigest()
            if initial_points_text is not None else None),
        "claim_boundary": (
            "The adapter proves identical RTL and SDC bytes plus an explicit effective "
            "configuration. It does not prove optimizer superiority."
        ),
    }
    expected_manifest = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if destination.exists():
        existing = destination / "generated-design-manifest.json"
        if not existing.is_file() or existing.read_text(encoding="utf-8") != expected_manifest:
            raise FileExistsError(f"generated design namespace identity conflict: {destination}")
        return manifest

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{namespace}.", dir=destination.parent))
    try:
        for relative, source in resolved:
            target = temporary / "src" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            if _sha256(target) != _sha256(source):
                raise OSError(f"RTL copy hash mismatch: {relative}")
        for relative, source in include_sources:
            target = temporary / "src" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            if _sha256(target) != _sha256(source):
                raise OSError(f"RTL include copy hash mismatch: {relative}")
        temporary_sdc = temporary / "constraint.sdc"
        shutil.copyfile(sdc, temporary_sdc)
        if _sha256(temporary_sdc) != identity["sdc_sha256"]:
            raise OSError("SDC copy hash mismatch")

        # Absolute paths are intentional: upstream AutoTuner does not forward
        # the platform runner's DESIGN_HOME.  All paths point inside this
        # content-addressed immutable adapter directory.
        (temporary / "config.mk").write_text(config_text, encoding="utf-8")
        if initial_points_text is not None:
            (temporary / "autotuner-best.json").write_text(
                initial_points_text, encoding="utf-8")
        (temporary / "generated-design-manifest.json").write_text(
            expected_manifest, encoding="utf-8")
        # The rename is atomic on the same filesystem.  A concurrent installer
        # either wins with the same identity or is rejected on its next check.
        try:
            temporary.rename(destination)
        except FileExistsError:
            existing = destination / "generated-design-manifest.json"
            if not existing.is_file() or existing.read_text(encoding="utf-8") != expected_manifest:
                raise
        return manifest
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def validate_generated_design_adapter(
    adapter_root: str | Path, *, orfs_root: str | Path,
) -> dict[str, Any]:
    """Verify every byte in an allowed untracked content-addressed adapter."""
    root = Path(orfs_root).expanduser().resolve()
    adapter = Path(adapter_root).expanduser().resolve()
    manifest_path = adapter / "generated-design-manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ValueError(f"generated design manifest is missing: {adapter}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema_version = manifest.get("schema_version")
    if schema_version not in {2, 3} or manifest.get("kind") != \
            "orfs-generated-design-identity":
        raise ValueError("unsupported generated design adapter schema")
    identity_keys = IDENTITY_KEYS_V3 if schema_version == 3 else IDENTITY_KEYS_V2
    identity = {key: manifest.get(key) for key in identity_keys}
    if (schema_version == 3 and manifest.get("configuration_policy_version") !=
            "exclusive-placement-density-v1"):
        raise ValueError("unsupported generated design configuration policy")
    identity_sha = _canonical_digest(identity)
    namespace = f"opv2_{str(manifest.get('top'))[:40]}_{identity_sha[:16]}"
    expected = root / "flow/designs" / str(manifest.get("platform")) / namespace
    if (manifest.get("identity_sha256") != identity_sha
            or manifest.get("namespace") != namespace
            or adapter != expected.resolve()
            or Path(str(manifest.get("adapter_root"))).resolve() != adapter
            or Path(str(manifest.get("config_path"))).resolve() != adapter / "config.mk"):
        raise ValueError("generated design adapter identity or location mismatch")
    expected_files = {
        "generated-design-manifest.json", "config.mk", "constraint.sdc",
    }
    config = adapter / "config.mk"
    sdc = adapter / "constraint.sdc"
    if (_sha256(config) != manifest.get("config_sha256")
            or _sha256(sdc) != manifest.get("sdc_sha256")
            or sdc.stat().st_size != manifest.get("sdc_size_bytes")):
        raise ValueError("generated design config or SDC integrity failure")
    for record in (*manifest.get("rtl_sources", ()),
                   *manifest.get("rtl_include_files", ())):
        relative = str(record.get("relative_path") or "")
        if (not relative or relative.startswith(("/", "../"))
                or ".." in Path(relative).parts):
            raise ValueError("unsafe generated design source path")
        path = adapter / "src" / relative
        expected_files.add(str(Path("src") / relative))
        if (not path.is_file() or path.is_symlink()
                or path.stat().st_size != record.get("size_bytes")
                or _sha256(path) != record.get("sha256")):
            raise ValueError(f"generated design source integrity failure: {relative}")
    initial = adapter / "autotuner-best.json"
    if manifest.get("autotuner_initial_points_sha256") is not None:
        expected_files.add("autotuner-best.json")
        if _sha256(initial) != manifest["autotuner_initial_points_sha256"]:
            raise ValueError("generated design initial-point integrity failure")
    observed_files = {
        str(path.relative_to(adapter)) for path in adapter.rglob("*") if path.is_file()
    }
    if observed_files != expected_files or any(path.is_symlink() for path in adapter.rglob("*")):
        raise ValueError("generated design adapter contains undeclared files or symlinks")
    return manifest


def generated_design_from_platform_plan(
    plan_path: str | Path, *, orfs_root: str | Path,
    autotuner_initial_points: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Install an adapter from an immutable ORFSRunner ``plan.json``."""
    path = Path(plan_path).expanduser().resolve()
    plan = json.loads(path.read_text(encoding="utf-8"))
    request = dict(plan.get("request") or {})
    workdir = Path(str(plan["workdir"])).expanduser().resolve()
    design = str(plan["design"])
    platform = str(request["platform"])
    staged_root = workdir / "designs" / "src" / design
    input_manifest_path = workdir / "design_input_manifest.json"
    if input_manifest_path.is_file():
        input_manifest = json.loads(input_manifest_path.read_text(encoding="utf-8"))
        source_order = list(input_manifest.get("source_order") or ())
        if not source_order:
            raise ValueError("platform design_input_manifest has no source order")
        rtl_files = {relative: staged_root / relative for relative in source_order}
        include_dirs = {
            relative: staged_root / relative
            for relative in input_manifest.get("include_dirs") or ()
        }
        frontend = input_manifest.get("synth_hdl_frontend")
    else:
        source = staged_root / f"{design}.v"
        rtl_files = {source.name: source}
        include_dirs = {}
        frontend = None
    sdc = workdir / "designs" / platform / design / "constraint.sdc"
    missing = [str(source) for source in rtl_files.values() if not source.is_file()]
    if missing:
        raise FileNotFoundError(f"platform plan RTL copies are missing: {missing}")
    return install_generated_design_adapter(
        orfs_root=orfs_root, platform=platform, top=design,
        rtl_files=rtl_files, sdc_path=sdc,
        clock_period_ns=float(request["clock_period_ns"]),
        core_utilization_pct=float(request["core_utilization_pct"]),
        place_density=float(request["place_density"]),
        or_seed=int(request["or_seed"]),
        flow_parameters=dict(request.get("flow_parameters") or {}),
        source_identity={
            "kind": "platform-orfs-plan",
            "plan_path": str(path),
            "plan_sha256": _sha256(path),
            "run_id": str(plan["run_id"]),
        },
        rtl_include_dirs=include_dirs,
        synth_hdl_frontend=frontend,
        autotuner_initial_points=autotuner_initial_points,
        design_options=dict(request.get("design_options") or {}),
    )


def generated_design_from_reference_design(
    reference: "ORFSReferenceDesign", *, orfs_root: str | Path,
    flow_parameters: Mapping[str, Any], or_seed: int,
    autotuner_initial_points: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Install the exact pinned reference bundle for an external optimizer.

    The logical paper identity remains ``reference.source_fingerprint``.  The
    returned namespace is an execution adapter whose identity additionally
    commits to the effective baseline parameters, implementation seed, and
    AutoTuner initial point.  Keeping those two identities explicit prevents
    an external tool from silently falling back to a similarly named native
    ORFS recipe with a different SDC.
    """
    root = reference.rtl_root.resolve()
    rtl_files = {
        str(path.resolve().relative_to(root)): path
        for path in reference.rtl_files
    }
    include_dirs = {
        str(path.resolve().relative_to(root)): path
        for path in reference.include_dirs
    }
    baseline = dict(flow_parameters)
    core_utilization = float(baseline.get(
        "core_utilization_pct",
        reference.native_baseline_overrides["core_utilization_pct"],
    ))
    place_density = float(reference.native_baseline_overrides.get(
        "place_density", baseline.get("place_density", .55),
    ))
    manifest = install_generated_design_adapter(
        orfs_root=orfs_root,
        platform=reference.platform,
        top=reference.top,
        rtl_files=rtl_files,
        rtl_include_dirs=include_dirs,
        sdc_path=reference.sdc_path,
        clock_period_ns=reference.clock_period_ns,
        core_utilization_pct=core_utilization,
        place_density=place_density,
        or_seed=or_seed,
        flow_parameters=baseline,
        source_identity={
            "kind": "pinned-orfs-reference-design",
            "logical_design": reference.design,
            "source_fingerprint": reference.source_fingerprint,
            "orfs_commit": reference.orfs_commit,
        },
        synth_hdl_frontend=reference.synth_hdl_frontend,
        autotuner_initial_points=autotuner_initial_points,
        design_options=reference.design_options,
    )
    return {
        **manifest,
        "kind": "pinned-orfs-reference-design-adapter",
        "logical_design": reference.design,
        "comparison_identity_sha256": reference.source_fingerprint,
        "source_fingerprint": reference.source_fingerprint,
        "orfs_commit": reference.orfs_commit,
        "design": reference.design,
    }
