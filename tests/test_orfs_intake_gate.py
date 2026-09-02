from __future__ import annotations

import json
from pathlib import Path

import pytest

from openroad_platform_execution.orfs_plugin import _require_executable_admission
from openroad_platform_execution import PluginRegistry


ROOT = Path(__file__).resolve().parents[1]


def test_orfs_without_reviewed_license_is_source_audit_only() -> None:
    lock = json.loads((ROOT / "integrations/orfs/orfs.intake.lock.json").read_text(encoding="utf-8"))
    assert lock["license"]["status"] == "red"
    assert lock["execution_class"] == "source-audit-only"
    with pytest.raises(PermissionError, match="source-audit-only"):
        _require_executable_admission()


def test_static_orfs_manifest_cannot_advertise_executable_capabilities() -> None:
    registry = PluginRegistry.from_directory(ROOT / "integrations/orfs")
    with pytest.raises(LookupError):
        registry.resolve("orfs", capability="eda.rtl_to_gds")
