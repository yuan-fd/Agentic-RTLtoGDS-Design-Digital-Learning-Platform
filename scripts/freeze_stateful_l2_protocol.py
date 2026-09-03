#!/usr/bin/env python3
"""Create the immutable r31 protocol for the repaired stateful L1/L2 study."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
for source in (ROOT, *sorted((ROOT / "packages").glob("*/src"))):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from openroad_platform_analysis import (  # noqa: E402
    build_stateful_l2_protocol, write_frozen_protocol,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _controller_source_snapshot() -> dict[str, object]:
    """Content-address the controller code that the protocol is freezing.

    A human label such as ``working-tree`` is not enough to reproduce a study.
    This mirrors the runner's source scope so the frozen protocol records the
    exact Python implementation that is later checked for each campaign cell.
    """
    roots = (
        ROOT / "apps/api", ROOT / "packages/analysis/src",
        ROOT / "packages/contracts/src", ROOT / "packages/execution/src",
        ROOT / "packages/scheduler/src",
    )
    files: list[Path] = []
    for pattern in (
        "*industrial_dse*.py", "*official_autotuner*.py",
        "calibrate_orfs_parameters.py", "prepare_pinned_orfs_toolchain.py",
    ):
        files.extend(sorted((ROOT / "scripts").glob(pattern)))
    for root in roots:
        files.extend(sorted(root.rglob("*.py")))
    records = [{"path": str(path.relative_to(ROOT)), "sha256": _sha256(path)}
               for path in sorted(set(files))]
    digest = hashlib.sha256(json.dumps(
        records, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"digest": digest, "file_count": len(records), "files": records}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--toolchain-lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=(
        ROOT / "studies/protocols/v2-industrial-dse-20260830-r31-stateful-l2.protocol.json"))
    args = parser.parse_args()
    calibration_path = args.calibration.expanduser().resolve()
    lock_path = args.toolchain_lock.expanduser().resolve()
    calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    source = {
        "controller": _controller_source_snapshot(),
        "freeze_script_sha256": _sha256(Path(__file__)),
    }
    protocol = build_stateful_l2_protocol(
        calibration_report=calibration, orfs_commit=str(lock["orfs_commit"]),
        toolchain_fingerprint=_sha256(lock_path), source_snapshot=source,
    )
    destination = write_frozen_protocol(args.output, protocol)
    print(json.dumps({"path": str(destination), "study_id": protocol["study_id"],
                      "protocol_digest": protocol["protocol_digest"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
