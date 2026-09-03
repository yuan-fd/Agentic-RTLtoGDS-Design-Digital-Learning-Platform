#!/usr/bin/env python3
"""Create or validate the exact ORFS worktree used by formal experiments."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(command: list[str], *, cwd: Path | None = None, check: bool = True):
    return subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=check)


def prepare(*, source: Path, output: Path, lock_path: Path,
            install_root: Path,
            binaries: dict[str, Path]) -> dict:
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    commit = lock["orfs_commit"]
    if not output.exists():
        output.parent.mkdir(parents=True, exist_ok=True)
        _run(["git", "-C", str(source), "worktree", "add", "--detach",
              str(output), commit])
    actual_commit = _run(["git", "rev-parse", "HEAD"], cwd=output).stdout.strip()
    if actual_commit != commit:
        raise ValueError("pinned ORFS worktree commit mismatch")
    for item in lock["patches"]:
        patch = ROOT / item["path"]
        if _sha256(patch) != item["sha256"]:
            raise ValueError(f"patch digest mismatch: {patch}")
    expected_diff = lock["orfs_binary_patch_sha256"]
    current_diff = _run(["git", "diff", "--binary"], cwd=output).stdout.encode()
    if not current_diff:
        for item in lock["patches"]:
            patch = ROOT / item["path"]
            _run(["git", "apply", "--check", str(patch)], cwd=output)
            _run(["git", "apply", str(patch)], cwd=output)
        current_diff = _run(["git", "diff", "--binary"], cwd=output).stdout.encode()
    if hashlib.sha256(current_diff).hexdigest() != expected_diff:
        raise ValueError("ORFS worktree contains an unregistered tracked diff")
    for item in lock["patches"]:
        patched = output / item["patched_file"]
        if _sha256(patched) != item["patched_file_sha256"]:
            raise ValueError(f"patched ORFS file mismatch: {patched}")

    links = {output / "tools/install": install_root}
    for link, target in links.items():
        if link.is_symlink():
            if link.resolve() != target.resolve():
                raise ValueError(f"toolchain symlink target mismatch: {link}")
        elif link.exists():
            raise ValueError(f"toolchain path exists but is not the pinned symlink: {link}")
        else:
            link.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(target.resolve(), link)
    binary_evidence = {}
    for name, path in binaries.items():
        digest = _sha256(path.resolve())
        expected = lock["binaries"][name]["sha256"]
        if digest != expected:
            raise ValueError(f"{name} binary digest mismatch")
        binary_evidence[name] = {"path": str(path.resolve()), "sha256": digest}
    status = _run(["git", "status", "--short"], cwd=output).stdout.splitlines()
    unexpected = [row for row in status
                  if row not in {" M flow/scripts/final_report.tcl",
                                 "?? toolchain-evidence.json"}]
    if unexpected:
        raise ValueError(f"unexpected pinned ORFS worktree entries: {unexpected}")
    evidence = {
        "schema_version": 1, "kind": "pinned-orfs-toolchain-evidence",
        "orfs_root": str(output.resolve()), "orfs_commit": actual_commit,
        "registered_diff_sha256": expected_diff, "git_status": status,
        "install_root": str(install_root.resolve()), "binaries": binary_evidence,
        "lock_path": str(lock_path.resolve()), "lock_sha256": _sha256(lock_path),
    }
    (output / "toolchain-evidence.json").write_text(
        json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path,
                        default=Path.home() / "OpenROAD-flow-scripts")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "var/toolchains/orfs-51ad1231-clean")
    parser.add_argument("--lock", type=Path,
                        default=ROOT / "integrations/orfs/orfs-industrial-v2.lock.json")
    parser.add_argument("--install-root", type=Path,
                        default=Path.home() / "OpenROAD-flow-scripts/tools/install")
    parser.add_argument("--openroad", type=Path, default=Path.home() / "bin/openroad")
    parser.add_argument("--yosys", type=Path, default=Path.home() / "bin/yosys")
    parser.add_argument("--klayout", type=Path, default=Path.home() / "bin/klayout")
    args = parser.parse_args()
    evidence = prepare(
        source=args.source.expanduser().resolve(), output=args.output.expanduser().resolve(),
        lock_path=args.lock.expanduser().resolve(),
        install_root=args.install_root.expanduser().resolve(),
        binaries={"openroad": args.openroad.expanduser().resolve(),
                  "yosys": args.yosys.expanduser().resolve(),
                  "klayout": args.klayout.expanduser().resolve()},
    )
    print(json.dumps(evidence, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
