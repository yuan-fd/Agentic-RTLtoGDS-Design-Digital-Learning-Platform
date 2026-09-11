"""Public construction helpers for the ORFS v1 plugin."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import uuid
from pathlib import Path
from typing import Mapping, Sequence

from openroad_platform_contracts import PluginManifest, RunRequest, RunStage, TaskSpec

from .toolchain import ToolchainConfig
from .orfs_parameters import validate_orfs_parameters


ORFS_PLUGIN_ID = "orfs"
ORFS_PLUGIN_VERSION = "1.2.0"


def _require_executable_admission() -> None:
    """Refuse an unreviewed external ORFS checkout before process creation."""
    lock = Path(__file__).resolve().parents[4] / "integrations/orfs/orfs.intake.lock.json"
    try:
        payload = json.loads(lock.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PermissionError("ORFS executable admission lock is missing or invalid") from exc
    allowed = {"admitted-bounded-runtime-plugin", "local-managed-runtime-toolchain"}
    if payload.get("execution_class") not in allowed:
        raise PermissionError("ORFS executable admission is not approved")


def build_orfs_task(
    rtl_path: str | Path,
    *,
    project_id: str,
    design_id: str,
    top: str | None = None,
    clock: str | None = None,
    platform_name: str = "nangate45",
    target_stage: str = "finish",
    clock_period_ns: float = 10.0,
    core_utilization_pct: float = 10.0,
    place_density: float = 0.45,
    or_seed: int = 1,
    minimum_die_size_um: float | None = None,
    stage_timeout_seconds: int = 3600,
    timeout_seconds: int = 7200,
    max_attempts: int = 1,
    task_id: str | None = None,
    labels: dict[str, str] | None = None,
    flow_parameters: dict[str, object] | None = None,
    rtl_files: Sequence[str | Path] | None = None,
    rtl_root: str | Path | None = None,
    rtl_include_dirs: Sequence[str | Path] = (),
    synth_hdl_frontend: str | None = None,
    design_options: dict[str, object] | None = None,
    sdc_path: str | Path | None = None,
    fast_route_tcl_path: str | Path | None = None,
) -> TaskSpec:
    """Create a TaskSpec with an immutable local RTL artifact reference."""

    source = Path(rtl_path).expanduser().resolve()
    if not source.is_file() or source.stat().st_size == 0:
        raise FileNotFoundError(f"RTL input is missing or empty: {source}")
    tuning = validate_orfs_parameters(flow_parameters or {}, platform=platform_name)
    bundle_paths = tuple(Path(item).expanduser().resolve() for item in (rtl_files or ()))
    bundle_root = Path(rtl_root).expanduser().resolve() if rtl_root is not None else None
    include_paths = tuple(Path(item).expanduser().resolve() for item in rtl_include_dirs)
    sdc = Path(sdc_path).expanduser().resolve() if sdc_path is not None else None
    fast_route = (Path(fast_route_tcl_path).expanduser().resolve()
                  if fast_route_tcl_path is not None else None)
    legacy = RunRequest(
        rtl_path=str(source), top=top, clock=clock,
        rtl_files=tuple(str(item) for item in bundle_paths),
        rtl_root=str(bundle_root) if bundle_root is not None else None,
        rtl_include_dirs=tuple(str(item) for item in include_paths),
        synth_hdl_frontend=synth_hdl_frontend,
        design_options=dict(design_options or {}),
        sdc_path=str(sdc) if sdc is not None else None,
        fast_route_tcl_path=str(fast_route) if fast_route is not None else None,
        clock_period_ns=clock_period_ns, platform=platform_name,
        target_stage=RunStage(target_stage),
        core_utilization_pct=core_utilization_pct,
        place_density=place_density,
        or_seed=or_seed,
        minimum_die_size_um=minimum_die_size_um,
        stage_timeout_seconds=stage_timeout_seconds,
        flow_parameters=tuning,
    )
    legacy.validate()
    first_physical_artifact = "netlist" if target_stage == "synth" else "odb"
    expected = [first_physical_artifact, "config", "toolchain_snapshot", "parameter_contract",
                "design_input_manifest", "run_result", "log"]
    if target_stage == "finish":
        expected.extend(("def", "netlist", "gds"))
    inputs = {
        "rtl": {
            "path": str(source),
            "size_bytes": source.stat().st_size,
            "sha256": _sha256(source),
        },
        "top": top,
        "clock": clock,
    }
    if bundle_paths:
        assert bundle_root is not None
        inputs["rtl_bundle"] = {
            "files": [{
                "path": str(path), "relative_path": str(path.relative_to(bundle_root)),
                "size_bytes": path.stat().st_size, "sha256": _sha256(path),
            } for path in bundle_paths],
            "include_dirs": [{
                "path": str(directory),
                "relative_path": str(directory.relative_to(bundle_root)),
                "headers": [{
                    "path": str(header),
                    "relative_path": str(header.relative_to(bundle_root)),
                    "size_bytes": header.stat().st_size, "sha256": _sha256(header),
                } for header in sorted(directory.rglob("*"))
                 if header.is_file() and header.suffix.lower() in {".v", ".sv", ".vh", ".svh"}],
            } for directory in include_paths],
            "synth_hdl_frontend": synth_hdl_frontend,
        }
    if sdc is not None:
        inputs["sdc"] = {
            "path": str(sdc), "size_bytes": sdc.stat().st_size, "sha256": _sha256(sdc),
        }
    if fast_route is not None:
        inputs["fast_route_tcl"] = {
            "path": str(fast_route), "size_bytes": fast_route.stat().st_size,
            "sha256": _sha256(fast_route),
        }
    task = TaskSpec(
        task_id=task_id or f"orfs-{uuid.uuid4().hex}",
        project_id=project_id,
        design_id=design_id,
        plugin_id=ORFS_PLUGIN_ID,
        inputs=inputs,
        parameters={
            "platform": legacy.platform,
            "target_stage": legacy.target_stage.value,
            "clock_period_ns": legacy.clock_period_ns,
            "core_utilization_pct": legacy.core_utilization_pct,
            "place_density": legacy.place_density,
            "or_seed": legacy.or_seed,
            "minimum_die_size_um": legacy.minimum_die_size_um,
            "stage_timeout_seconds": legacy.stage_timeout_seconds,
            "flow_parameters": tuning,
            "design_options": legacy.design_options,
        },
        resources={"toolchain_profile": "default"},
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
        expected_artifacts=tuple(expected),
        labels=dict(labels or {}),
    )
    task.validate()
    return task


def orfs_plugin_manifest(
    toolchain: ToolchainConfig,
    *,
    python_executable: str | Path = sys.executable,
    default_timeout_seconds: int = 21_600,
) -> PluginManifest:
    """Bind the repository adapter to one explicit immutable toolchain profile."""

    _require_executable_admission()

    adapter = Path(__file__).with_name("orfs_adapter.py").resolve()
    environment = {
        key: os.environ[key]
        for key in toolchain.inherit_environment
        if key in os.environ
    }
    environment.update(toolchain.environment)
    environment.update({
        "ORFS_ROOT": str(toolchain.orfs_root),
        "OPENROAD_BIN": str(toolchain.openroad_bin),
        "YOSYS_BIN": str(toolchain.yosys_bin),
        "OPENROAD_PLATFORM_TOOLCHAIN_PROFILE": toolchain.name,
    })
    # Operator-owned resource policy is captured in the immutable plugin
    # manifest so local and Ray workers receive the same limit. It is never
    # accepted from a browser or TaskSpec payload.
    if "OPENROAD_PLATFORM_ORFS_CORES" in os.environ:
        environment["OPENROAD_PLATFORM_ORFS_CORES"] = os.environ[
            "OPENROAD_PLATFORM_ORFS_CORES"]
    if toolchain.klayout_bin is not None:
        environment["KLAYOUT_BIN"] = str(toolchain.klayout_bin)
    manifest = PluginManifest(
        plugin_id=ORFS_PLUGIN_ID,
        plugin_version=ORFS_PLUGIN_VERSION,
        adapter_entry=(str(Path(python_executable).resolve()), str(adapter)),
        capabilities=("eda.orfs", "eda.rtl_to_gds"),
        supported_arch=(platform.machine(),),
        input_schema={
            "type": "object",
            "required": ["rtl"],
            "properties": {
                "rtl": {
                    "type": "object",
                    "required": ["path", "size_bytes", "sha256"],
                },
                "top": {"type": ["string", "null"]},
                "clock": {"type": ["string", "null"]},
                "rtl_bundle": {"type": "object"},
                "sdc": {"type": "object"},
                "fast_route_tcl": {"type": "object"},
            },
        },
        output_schema={"type": "object", "required": ["status", "artifacts"]},
        required_tools=("make", "git", "openroad", "yosys"),
        default_timeout_seconds=default_timeout_seconds,
        artifact_rules=tuple(
            {"kind": kind, "required": kind == "log"}
            for kind in (
                "odb", "def", "netlist", "gds", "log", "report", "config",
                "toolchain_snapshot", "parameter_contract", "run_result", "other",
                "layout_view", "design_input_manifest",
            )
        ),
        environment=environment,
    )
    manifest.validate()
    return manifest


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
