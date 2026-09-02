from __future__ import annotations

import json
from pathlib import Path

import pytest

from openroad_platform_execution.orfs_plugin import _require_executable_admission
from openroad_platform_execution import PluginRegistry


ROOT = Path(__file__).resolve().parents[1]


def test_server_managed_orfs_has_local_execution_authorization() -> None:
    lock = json.loads((ROOT / "integrations/orfs/orfs.intake.lock.json").read_text(encoding="utf-8"))
    assert lock["license"]["status"] == "local-managed"
    assert lock["execution_class"] == "local-managed-runtime-toolchain"
    assert lock["authorization"]["scope"] == "server-local execution only"
    _require_executable_admission()


def test_static_orfs_manifest_is_registered_as_execution_backend() -> None:
    registry = PluginRegistry.from_directory(ROOT / "integrations/orfs")
    assert registry.resolve("orfs", capability="eda.rtl_to_gds").plugin_id == "orfs"
