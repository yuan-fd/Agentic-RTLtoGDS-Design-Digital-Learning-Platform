#!/usr/bin/env python3
"""Durable controller worker for long-running v2 DSE checkpoints."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api.app import ApiState  # noqa: E402


class ControllerHeartbeat:
    def __init__(self, path: Path, worker_id: str):
        self.path, self.worker_id = path, worker_id
        self.active_pipeline: str | None = None
        self.status = "idle"
        self._lock = threading.Lock()

    def write(self) -> None:
        now = datetime.now(timezone.utc)
        payload = {
            "schema_version": 1, "pid": os.getpid(), "worker_id": self.worker_id,
            "status": self.status, "active_run": self.active_pipeline,
            "active_pipeline": self.active_pipeline, "updated_at": now.isoformat(),
            "updated_at_epoch": now.timestamp(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(json.dumps(payload, sort_keys=True) + "\n",
                                 encoding="utf-8")
            temporary.replace(self.path)


def _next_pipeline(state: ApiState):
    terminal = {"completed", "diagnosis_required", "failed"}
    records = []
    for kind in ("external-optimizer-loop-v1", "bo-gp-closed-loop-v2"):
        records.extend(state.pipeline_checkpoints.list(pipeline_kind=kind, limit=1000))
    pending = [item for item in records
               if item.get("state", {}).get("status") not in terminal]
    return sorted(pending, key=lambda item: item["updated_at"])[0] if pending else None


def main(argv: list[str] | None = None) -> int:
    local_state = Path(os.environ.get(
        "OPENROAD_PLATFORM_LOCAL_STATE", f"/tmp/openroad-platform-{os.getuid()}"))
    parser = argparse.ArgumentParser(description="v2 DSE controller worker")
    parser.add_argument("--db", type=Path, default=ROOT / "var" / "platform.db")
    parser.add_argument("--upload-root", type=Path, default=ROOT / "var" / "uploads")
    parser.add_argument("--design-root", type=Path, default=ROOT / "var" / "designs")
    parser.add_argument("--legacy-root", type=Path,
                        default=Path(os.environ.get("ICCAD_ROOT", ROOT.parent / "iccad")))
    parser.add_argument("--runtime-db", type=Path,
                        default=Path(os.environ.get(
                            "OPENROAD_PLATFORM_RUNTIME_DB", local_state / "runtime.db")))
    parser.add_argument("--optimization-db", type=Path,
                        default=Path(os.environ.get(
                            "OPENROAD_PLATFORM_OPTIMIZATION_DB", local_state / "optimization.db")))
    parser.add_argument("--orfs-root", type=Path,
                        default=Path(os.environ.get(
                            "ORFS_ROOT", ROOT.parent / "OpenROAD-flow-scripts")))
    parser.add_argument("--heartbeat", type=Path,
                        default=local_state / "dse-controller.heartbeat.json")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    if args.poll_seconds <= 0:
        parser.error("--poll-seconds must be positive")
    lock_path = args.heartbeat.with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_stream = lock_path.open("a+")
    try:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"DSE controller worker is already active ({lock_path})", file=sys.stderr)
        return 2
    state = ApiState(
        args.db, args.upload_root, args.orfs_root,
        design_root=args.design_root, legacy_root=args.legacy_root,
        runtime_db_path=args.runtime_db, optimization_db_path=args.optimization_db,
        load_taiwei_plugin=False,
    )
    heartbeat = ControllerHeartbeat(
        args.heartbeat, f"dse-{socket.gethostname()}-{os.getpid()}")
    stop = threading.Event()

    def request_stop(_signum=None, _frame=None):
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    def pulse():
        while not stop.wait(2):
            heartbeat.write()

    thread = threading.Thread(target=pulse, daemon=True, name="dse-controller-heartbeat")
    thread.start(); heartbeat.write()
    try:
        while not stop.is_set():
            checkpoint = _next_pipeline(state)
            if checkpoint is None:
                if args.once:
                    break
                stop.wait(args.poll_seconds); continue
            heartbeat.active_pipeline = checkpoint["pipeline_id"]
            heartbeat.status = "running"; heartbeat.write()
            try:
                if checkpoint["pipeline_kind"] == "external-optimizer-loop-v1":
                    state.advance_external_optimizer_loop(
                        checkpoint["pipeline_id"], owner_id=checkpoint.get("owner_id"),
                        include_legacy=True, execute=True)
                else:
                    state.run_bayesian_closed_loop_to_boundary(
                        checkpoint["pipeline_id"], {"max_transitions": 1},
                        owner_id=checkpoint.get("owner_id"), include_legacy=True)
            except ValueError as exc:
                # Another controller can only win through the optimistic
                # revision gate; the losing worker performs no blind overwrite.
                if "revision conflict" not in str(exc):
                    print(f"DSE controller error: {exc}", file=sys.stderr, flush=True)
                    stop.wait(args.poll_seconds)
            except Exception as exc:
                print(f"DSE controller error: {type(exc).__name__}: {exc}",
                      file=sys.stderr, flush=True)
                stop.wait(args.poll_seconds)
            finally:
                heartbeat.active_pipeline = None
                heartbeat.status = "idle"; heartbeat.write()
            if args.once:
                break
    finally:
        stop.set(); heartbeat.status = "stopped"; heartbeat.write()
        thread.join(timeout=3)
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)
        lock_stream.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
