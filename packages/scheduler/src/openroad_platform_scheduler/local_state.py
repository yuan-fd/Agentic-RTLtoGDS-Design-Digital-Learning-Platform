"""Crash-safe local SQLite state with validated shared-filesystem mirrors.

SQLite WAL uses a shared-memory file and must not be treated as a portable
database on network/FUSE filesystems.  Long-running DSE cells therefore keep
their live databases on a node-local filesystem while publishing alternating,
content-verified backup slots beside the durable experiment artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import uuid


NETWORK_FILESYSTEMS = frozenset({
    "fuse.glusterfs", "glusterfs", "nfs", "nfs4", "cifs", "smb3",
    "fuse.sshfs", "ceph", "fuse.ceph", "lustre",
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest_bytes(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    with temporary.open("rb") as stream:
        os.fsync(stream.fileno())
    temporary.replace(path)


def filesystem_type(path: Path) -> str:
    """Return the Linux mount filesystem type for ``path``.

    Parsing mountinfo avoids shelling out and uses the longest matching mount
    point, which is important when a local scratch mount sits below ``/var``.
    """
    resolved = path.expanduser().resolve()
    probe = resolved if resolved.exists() else next(
        parent for parent in (resolved, *resolved.parents) if parent.exists())
    best: tuple[int, str] | None = None
    for line in Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if "-" not in fields or len(fields) < 10:
            continue
        separator = fields.index("-")
        mount_point = Path(fields[4].replace("\\040", " ")).resolve()
        try:
            probe.relative_to(mount_point)
        except ValueError:
            continue
        candidate = (len(str(mount_point)), fields[separator + 1])
        if best is None or candidate[0] > best[0]:
            best = candidate
    if best is None:
        raise RuntimeError(f"cannot resolve filesystem type for {resolved}")
    return best[1]


def require_local_sqlite_root(path: Path) -> str:
    fs_type = filesystem_type(path)
    if fs_type in NETWORK_FILESYSTEMS or fs_type.startswith("fuse."):
        raise ValueError(
            f"live SQLite state requires a node-local filesystem; {path} uses {fs_type}"
        )
    return fs_type


@dataclass(frozen=True)
class StateSnapshot:
    sequence: int
    slot: int
    database_count: int
    manifest_path: Path


class LocalStateMirror:
    """Manage one cell's node-local state and two validated durable mirrors."""

    SCHEMA_VERSION = 1

    def __init__(self, *, local_root: Path, shared_root: Path, binding_sha256: str):
        self.local_root = local_root.expanduser().resolve()
        self.shared_root = shared_root.expanduser().resolve()
        self.binding_sha256 = binding_sha256
        self.mirror_root = self.shared_root / "state-mirror"
        self.local_binding = self.local_root / "state-binding.json"
        self.local_root.mkdir(parents=True, exist_ok=True)
        self.local_filesystem = require_local_sqlite_root(self.local_root)

    def prepare(self) -> dict:
        """Bind the local directory and restore the newest valid mirror if empty."""
        binding = {
            "schema_version": self.SCHEMA_VERSION,
            "binding_sha256": self.binding_sha256,
            "storage_policy": "node-local-sqlite-with-two-slot-verified-mirror-v1",
            "local_filesystem": self.local_filesystem,
        }
        if self.local_binding.exists():
            existing = json.loads(self.local_binding.read_text(encoding="utf-8"))
            if existing != binding:
                raise ValueError("local state root is bound to a different experiment cell")
            return {**binding, "restored": False, "reused_local_state": True}

        if any(self.local_root.iterdir()):
            raise ValueError("unbound local state root is not empty")
        restored = self._restore_latest_valid()
        _atomic_json(self.local_binding, binding)
        return {**binding, "restored": restored, "reused_local_state": False}

    def snapshot(self) -> StateSnapshot:
        pointer = self._pointer()
        sequence = int(pointer.get("sequence", 0)) + 1
        slot = sequence % 2
        slot_root = self.mirror_root / f"slot-{slot}"
        staging = self.mirror_root / f".slot-{slot}.{uuid.uuid4().hex}.tmp"
        staging.mkdir(parents=True, exist_ok=False)
        records = []
        try:
            for source in sorted(self.local_root.glob("*.db")):
                local_backup = self.local_root / f".{source.name}.{uuid.uuid4().hex}.backup"
                source_connection = sqlite3.connect(source)
                destination_connection = sqlite3.connect(local_backup)
                try:
                    source_connection.backup(destination_connection)
                finally:
                    destination_connection.close()
                    source_connection.close()
                destination = staging / source.name
                shutil.copyfile(local_backup, destination)
                local_backup.unlink()
                records.append({
                    "name": source.name,
                    "size_bytes": destination.stat().st_size,
                    "sha256": _digest_bytes(destination),
                })
            if not records:
                raise ValueError("cannot mirror local state before databases exist")
            manifest = {
                "schema_version": self.SCHEMA_VERSION,
                "binding_sha256": self.binding_sha256,
                "sequence": sequence,
                "slot": slot,
                "created_at": _now(),
                "databases": records,
            }
            _atomic_json(staging / "manifest.json", manifest)
            if slot_root.exists():
                retired = self.mirror_root / f".retired-{slot}.{uuid.uuid4().hex}"
                slot_root.replace(retired)
                staging.replace(slot_root)
                shutil.rmtree(retired)
            else:
                staging.replace(slot_root)
            _atomic_json(self.mirror_root / "latest.json", {
                "schema_version": self.SCHEMA_VERSION,
                "binding_sha256": self.binding_sha256,
                "sequence": sequence,
                "slot": slot,
                "manifest_sha256": _digest_bytes(slot_root / "manifest.json"),
            })
            return StateSnapshot(sequence, slot, len(records), slot_root / "manifest.json")
        except BaseException:
            if staging.exists():
                shutil.rmtree(staging)
            raise

    def _pointer(self) -> dict:
        path = self.mirror_root / "latest.json"
        if not path.is_file():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return value if value.get("binding_sha256") == self.binding_sha256 else {}

    def _restore_latest_valid(self) -> bool:
        pointer = self._pointer()
        preferred = pointer.get("slot")
        slots = ([int(preferred), 1 - int(preferred)]
                 if preferred in {0, 1} else [0, 1])
        candidates = []
        for slot in slots:
            manifest_path = self.mirror_root / f"slot-{slot}" / "manifest.json"
            if not manifest_path.is_file():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest.get("binding_sha256") != self.binding_sha256:
                    continue
                if all(
                    (manifest_path.parent / row["name"]).is_file()
                    and (manifest_path.parent / row["name"]).stat().st_size == row["size_bytes"]
                    and _digest_bytes(manifest_path.parent / row["name"]) == row["sha256"]
                    for row in manifest.get("databases", [])
                ):
                    candidates.append((int(manifest["sequence"]), manifest_path, manifest))
            except (KeyError, OSError, ValueError, json.JSONDecodeError):
                continue
        if not candidates:
            return False
        _, manifest_path, manifest = max(candidates, key=lambda item: item[0])
        for row in manifest["databases"]:
            shutil.copyfile(manifest_path.parent / row["name"], self.local_root / row["name"])
        return True


def resolve_mirrored_database(shared_root: Path, name: str) -> Path:
    """Return a hash-verified mirrored DB, or a direct legacy-cell DB path."""
    root = shared_root.expanduser().resolve()
    mirror_root = root / "state-mirror"
    pointer_path = mirror_root / "latest.json"
    if not pointer_path.is_file():
        return root / name
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        preferred = int(pointer["slot"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        preferred = -1
        pointer = {}
    slots = ([preferred, 1 - preferred] if preferred in {0, 1} else [0, 1])
    valid = []
    for slot in slots:
        manifest_path = mirror_root / f"slot-{slot}" / "manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            if (slot == preferred and pointer.get("manifest_sha256")
                    and _digest_bytes(manifest_path) != pointer["manifest_sha256"]):
                continue
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            records = {row["name"]: row for row in manifest["databases"]}
            record = records[name]
            database = manifest_path.parent / name
            if (database.stat().st_size != record["size_bytes"]
                    or _digest_bytes(database) != record["sha256"]):
                continue
            valid.append((int(manifest["sequence"]), database))
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
    if not valid:
        raise ValueError(f"no valid mirrored {name} exists in {root}")
    return max(valid, key=lambda item: item[0])[1]
