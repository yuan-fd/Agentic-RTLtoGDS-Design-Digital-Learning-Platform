from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from openroad_platform_scheduler.local_state import (
    LocalStateMirror, resolve_mirrored_database,
)


def _write_database(path: Path, value: str) -> None:
    connection = sqlite3.connect(path)
    connection.execute("create table if not exists evidence(value text not null)")
    connection.execute("delete from evidence")
    connection.execute("insert into evidence values (?)", (value,))
    connection.commit()
    connection.close()


def _read_database(path: Path) -> str:
    connection = sqlite3.connect(path)
    value = connection.execute("select value from evidence").fetchone()[0]
    connection.close()
    return value


def test_two_slot_mirror_restores_latest_valid_snapshot(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    local = tmp_path / "local"
    shared.mkdir()
    mirror = LocalStateMirror(local_root=local, shared_root=shared, binding_sha256="a" * 64)
    assert mirror.prepare()["restored"] is False
    _write_database(local / "runtime.db", "first")
    first = mirror.snapshot()
    _write_database(local / "runtime.db", "second")
    second = mirror.snapshot()
    assert first.slot != second.slot

    restored_root = tmp_path / "restored"
    restored = LocalStateMirror(
        local_root=restored_root, shared_root=shared, binding_sha256="a" * 64)
    assert restored.prepare()["restored"] is True
    assert _read_database(restored_root / "runtime.db") == "second"
    assert _read_database(resolve_mirrored_database(shared, "runtime.db")) == "second"


def test_mirror_falls_back_when_latest_slot_is_corrupt(tmp_path: Path) -> None:
    shared = tmp_path / "shared"; shared.mkdir()
    local = tmp_path / "local"
    mirror = LocalStateMirror(local_root=local, shared_root=shared, binding_sha256="b" * 64)
    mirror.prepare()
    _write_database(local / "runtime.db", "safe")
    first = mirror.snapshot()
    _write_database(local / "runtime.db", "new")
    latest = mirror.snapshot()
    (latest.manifest_path.parent / "runtime.db").write_bytes(b"corrupt")

    restored_root = tmp_path / "restored"
    restored = LocalStateMirror(
        local_root=restored_root, shared_root=shared, binding_sha256="b" * 64)
    assert restored.prepare()["restored"] is True
    assert _read_database(restored_root / "runtime.db") == "safe"
    assert _read_database(resolve_mirrored_database(shared, "runtime.db")) == "safe"
    assert json.loads(first.manifest_path.read_text())["sequence"] == first.sequence


def test_local_state_binding_rejects_cross_cell_reuse(tmp_path: Path) -> None:
    shared = tmp_path / "shared"; shared.mkdir()
    local = tmp_path / "local"
    LocalStateMirror(
        local_root=local, shared_root=shared, binding_sha256="c" * 64).prepare()
    with pytest.raises(ValueError, match="different experiment"):
        LocalStateMirror(
            local_root=local, shared_root=shared, binding_sha256="d" * 64).prepare()
