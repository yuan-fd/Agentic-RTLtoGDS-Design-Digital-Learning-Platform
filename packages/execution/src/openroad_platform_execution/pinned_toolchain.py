"""Read-only integrity gate for a frozen ORFS experiment toolchain."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from .orfs_generated_design import validate_generated_design_adapter


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(root: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False,
    )
    if completed.returncode:
        raise ValueError(
            f"pinned ORFS git check failed: {completed.stderr.decode(errors='replace')[:300]}")
    return completed.stdout


def validate_pinned_orfs_toolchain(
    orfs_root: str | Path,
    lock_path: str | Path,
) -> dict[str, Any]:
    """Verify source, registered patch and executables without mutating them."""
    root = Path(orfs_root).expanduser().resolve()
    lock_file = Path(lock_path).expanduser().resolve()
    evidence_file = root / "toolchain-evidence.json"
    if not root.is_dir() or not lock_file.is_file() or not evidence_file.is_file():
        raise ValueError("pinned ORFS root, lock, or toolchain evidence is missing")
    lock = json.loads(lock_file.read_text(encoding="utf-8"))
    evidence = json.loads(evidence_file.read_text(encoding="utf-8"))
    actual_commit = _git(root, "rev-parse", "HEAD").decode().strip()
    if actual_commit != lock.get("orfs_commit"):
        raise ValueError("pinned ORFS commit mismatch")
    diff_sha = hashlib.sha256(_git(root, "diff", "--binary")).hexdigest()
    if diff_sha != lock.get("orfs_binary_patch_sha256"):
        raise ValueError("pinned ORFS tracked diff does not match the registered patch")
    for patch in lock.get("patches", []):
        patched_file = root / patch["patched_file"]
        if (not patched_file.is_file()
                or _sha256(patched_file) != patch["patched_file_sha256"]):
            raise ValueError(f"pinned ORFS patched file mismatch: {patched_file}")
    if Path(evidence.get("orfs_root", "")).resolve() != root:
        raise ValueError("toolchain evidence is bound to another ORFS root")
    if evidence.get("orfs_commit") != actual_commit:
        raise ValueError("toolchain evidence commit mismatch")
    if evidence.get("registered_diff_sha256") != diff_sha:
        raise ValueError("toolchain evidence patch digest mismatch")
    if evidence.get("lock_sha256") != _sha256(lock_file):
        raise ValueError("toolchain lock digest mismatch")
    for name, expected in lock.get("binaries", {}).items():
        record = (evidence.get("binaries") or {}).get(name) or {}
        binary = Path(record.get("path", "")).expanduser().resolve()
        if (not binary.is_file() or _sha256(binary) != expected.get("sha256")
                or record.get("sha256") != expected.get("sha256")):
            raise ValueError(f"pinned {name} binary digest mismatch")
    status = _git(root, "status", "--short").decode().splitlines()
    allowed_status = {" M flow/scripts/final_report.tcl", "?? toolchain-evidence.json"}
    generated_adapters = []
    unexpected = []
    for item in status:
        if item in allowed_status:
            continue
        relative = item[3:].rstrip("/") if item.startswith("?? ") else ""
        parts = Path(relative).parts
        if (len(parts) == 4 and parts[:2] == ("flow", "designs")
                and parts[3].startswith("opv2_")):
            try:
                manifest = validate_generated_design_adapter(
                    root / relative, orfs_root=root)
                generated_adapters.append({
                    "path": relative,
                    "identity_sha256": manifest["identity_sha256"],
                    "config_sha256": manifest["config_sha256"],
                    "sdc_sha256": manifest["sdc_sha256"],
                })
                continue
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                pass
        unexpected.append(item)
    if unexpected:
        raise ValueError(f"pinned ORFS worktree has unregistered entries: {unexpected}")
    result = {
        **evidence,
        "validation_kind": "read-only-pinned-orfs-validation",
        "validated": True,
        "observed_git_status": status,
        "validated_generated_design_adapters": generated_adapters,
        "lock_sha256": _sha256(lock_file),
    }
    result["validation_fingerprint"] = hashlib.sha256(json.dumps(
        result, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    return result
