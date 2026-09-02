from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_orfs_agent_source_lock_is_pinned_and_formally_admitted():
    lock = json.loads((ROOT / "integrations/orfs_agent/source.lock.json").read_text())
    source = ROOT / lock["cache_path"]
    assert lock["license"] == "BSD-3-Clause"
    assert lock["admission_status"] == "admitted-bounded-runtime-smoke-no-performance-claim"
    assert len(lock["commit"]) == 40
    assert source.is_dir()
    assert (source / "LICENSE").is_file()
    assert "BSD 3-Clause License" in (source / "LICENSE").read_text()


def test_api_admits_orfs_agent_only_through_the_reviewed_source_lock():
    source = (ROOT / "apps/api/app.py").read_text(encoding="utf-8")
    assert "admitted-bounded-runtime-smoke-no-performance-claim" in source
    assert "manifests.append(orfs_agent_plugin_manifest(" in source


def test_statetune_is_explicitly_blocked_from_executable_plugin_admission():
    lock = json.loads((ROOT / "integrations/statetune/source.lock.json").read_text())
    source = ROOT / lock["cache_path"]
    assert lock["admission_status"] == "source-audit-only"
    assert lock["license_status"] == "not_declared_in_checked_revision"
    assert source.is_dir()
    assert not any((source / name).is_file() for name in ("LICENSE", "COPYING", "NOTICE"))
    assert not (ROOT / "integrations/statetune/statetune.plugin.json").exists()
