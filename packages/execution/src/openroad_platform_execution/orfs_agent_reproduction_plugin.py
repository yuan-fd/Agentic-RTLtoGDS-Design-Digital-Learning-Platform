"""Thin manifest/task factory for the full upstream ORFS-Agent reproduction mode.

The platform owns only the immutable task envelope and isolated process.  The
12-dimensional search and GP/EI proposals remain in the pinned upstream
ORFS-Agent source.  This module must not acquire an optimiser implementation.
"""

from __future__ import annotations

import hashlib
import platform
import sys
import uuid
from pathlib import Path
from typing import Any, Mapping

from openroad_platform_contracts import PluginManifest, TaskSpec


ORFS_AGENT_REPRODUCTION_PLUGIN_ID = "orfs-agent-paper-reproduction"
ORFS_AGENT_REPRODUCTION_VERSION = "2025.1-paper"
ORFS_AGENT_COMMIT = "730f1fa11f9c17c0aaac332412af2b2538f42e9b"
ORFS_PAPER_COMMIT = "ce8d36a7fef0ab9c47d183bcf078bce0f60f5a54"
UPSTREAM_PARAMETERS = (
    "CLK", "UTIL", "TNS_End_Percent", "GP_PAD", "DP_PAD", "DPO",
    "PIN_ADJ", "UP_ADJ", "LB_ADDON", "HIER_SYNTH", "CTS_CSIZE", "CTS_CDIA",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_orfs_agent_reproduction_task(*, project_id: str, design_id: str,
                                       design: str, platform_name: str,
                                       candidate: Mapping[str, Any],
                                       timeout_seconds: int = 10_800,
                                       task_id: str | None = None) -> TaskSpec:
    """Build a one-candidate Runtime task without changing its 12-D identity."""
    if design not in {"aes", "ibex", "jpeg"} or platform_name not in {"asap7", "sky130hd"}:
        raise ValueError("paper reproduction supports aes/ibex/jpeg on asap7/sky130hd")
    if set(candidate) != set(UPSTREAM_PARAMETERS):
        raise ValueError("candidate must retain all 12 upstream ORFS-Agent parameters")
    task = TaskSpec(
        task_id=task_id or f"orfs-agent-paper-{uuid.uuid4().hex}",
        project_id=project_id,
        design_id=design_id,
        plugin_id=ORFS_AGENT_REPRODUCTION_PLUGIN_ID,
        inputs={"mode": "run_candidate", "design": design, "platform": platform_name,
                "candidate": dict(candidate)},
        parameters={"protocol": "orfs-agent-paper-reproduction-v1",
                    "candidate_sha256": hashlib.sha256(repr(sorted(candidate.items())).encode()).hexdigest()},
        resources={"toolchain_profile": "orfs-agent-paper-pinned"},
        timeout_seconds=timeout_seconds,
        max_attempts=1,
        expected_artifacts=("optimizer_input_manifest", "optimizer_dataset", "upstream_source_lock", "log", "report"),
        labels={"reproduction_mode": "variable-clock-upstream-semantics"},
    )
    task.validate()
    return task


def orfs_agent_reproduction_manifest(*, source: str | Path, paper_orfs: str | Path,
                                     openroad_bin: str | Path, yosys_bin: str | Path,
                                     python_executable: str | Path = sys.executable,
                                     default_timeout_seconds: int = 10_800,
                                     runtime_environment: Mapping[str, str] | None = None) -> PluginManifest:
    """Bind one pinned source and paper toolchain to an isolated adapter."""
    source_root, paper_root = Path(source).expanduser().resolve(), Path(paper_orfs).expanduser().resolve()
    openroad, yosys = Path(openroad_bin).expanduser().resolve(), Path(yosys_bin).expanduser().resolve()
    for name, path in (("ORFS-Agent source", source_root), ("paper ORFS", paper_root),
                       ("OpenROAD", openroad), ("Yosys", yosys)):
        if not path.exists():
            raise FileNotFoundError(f"{name} is absent: {path}")
    adapter = Path(__file__).resolve().parents[4] / "integrations/orfs_agent/orfs_agent_reproduction_adapter.py"
    environment = {
        "ORFS_AGENT_SOURCE": str(source_root),
        "ORFS_AGENT_EXPECTED_COMMIT": ORFS_AGENT_COMMIT,
        "ORFS_AGENT_PAPER_ORFS_ROOT": str(paper_root),
        "ORFS_AGENT_PAPER_ORFS_COMMIT": ORFS_PAPER_COMMIT,
        "OPENROAD_BIN": str(openroad), "YOSYS_BIN": str(yosys),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PATH": f"{openroad.parent}:{yosys.parent}:/usr/bin:/bin",
    }
    # A paper toolchain may require a pinned user-space library prefix.  It is
    # passed by the operator-owned toolchain profile, never accepted from a
    # browser task.  The default remains empty so a static/self-contained
    # future build needs no special case.
    for key, value in dict(runtime_environment or {}).items():
        if key not in {"LD_LIBRARY_PATH", "LIBRARY_PATH", "TCLLIBPATH"}:
            raise ValueError(f"unsupported paper toolchain environment key: {key}")
        if not isinstance(value, str):
            raise ValueError(f"paper toolchain environment {key} must be a string")
        environment[key] = value
    manifest = PluginManifest(
        plugin_id=ORFS_AGENT_REPRODUCTION_PLUGIN_ID,
        plugin_version=ORFS_AGENT_REPRODUCTION_VERSION,
        adapter_entry=(str(Path(python_executable).resolve()), str(adapter)),
        capabilities=("optimizer.l2.execute-upstream-candidate", "optimizer.l2.paper-reproduction"),
        supported_arch=(platform.machine(),),
        input_schema={"type": "object", "required": ["mode", "design", "platform", "candidate"]},
        output_schema={"type": "object", "required": ["status", "artifacts", "provenance"]},
        required_tools=("make", "git", "openroad", "yosys"),
        default_timeout_seconds=default_timeout_seconds,
        artifact_rules=(
            {"kind": "optimizer_input_manifest", "required": True},
            {"kind": "optimizer_dataset", "required": True},
            {"kind": "upstream_source_lock", "required": True},
            {"kind": "log", "required": True},
            {"kind": "report", "required": True},
        ),
        environment=environment,
    )
    manifest.validate()
    return manifest
