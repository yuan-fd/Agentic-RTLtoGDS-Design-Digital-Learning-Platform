from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from openroad_platform_contracts import RunRequest, RunResult, RunStatus, RuntimeStatus


TERMINAL = {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}


@dataclass(frozen=True)
class Job:
    id: str
    status: RunStatus
    request: RunRequest
    created_at: str
    updated_at: str
    claimed_by: str | None = None
    heartbeat_at: str | None = None
    result: dict | None = None
    error: str | None = None
    runtime_run_id: str | None = None


class JobStore:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def submit(self, request: RunRequest) -> Job:
        request.validate()
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO jobs
                   (id, status, request_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (request.run_id, RunStatus.QUEUED.value,
                 json.dumps(request.to_dict(), ensure_ascii=False), now, now),
            )
            self._event(connection, request.run_id, "submitted", {})
        return self.get(request.run_id)

    def get(self, job_id: str) -> Job:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown job: {job_id}")
        return self._job(row)

    def list(self, *, limit: int = 50) -> list[Job]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._job(row) for row in rows]

    def claim_next(self, worker_id: str) -> Job | None:
        now = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT id FROM jobs WHERE status = ? ORDER BY created_at LIMIT 1",
                (RunStatus.QUEUED.value,),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            updated = connection.execute(
                """UPDATE jobs SET status = ?, claimed_by = ?, heartbeat_at = ?,
                   updated_at = ? WHERE id = ? AND status = ?""",
                (RunStatus.PREPARING.value, worker_id, now, now, row["id"],
                 RunStatus.QUEUED.value),
            )
            if updated.rowcount != 1:
                connection.rollback()
                return None
            self._event(connection, row["id"], "claimed", {"worker_id": worker_id})
            connection.commit()
        return self.get(row["id"])

    def mark_running(self, job_id: str) -> None:
        self._transition(job_id, {RunStatus.PREPARING}, RunStatus.RUNNING, "started")

    def bind_runtime_run(self, job_id: str, runtime_run_id: str) -> Job:
        """Record a non-authoritative link to the sole Runtime run.

        The old jobs table is retained only for backward-compatible reads and
        cancellation intake.  It must never point one job at multiple Runtime
        runs.
        """
        if not runtime_run_id:
            raise ValueError("runtime_run_id is required")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT runtime_run_id FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown job: {job_id}")
            current = row["runtime_run_id"]
            if current not in {None, runtime_run_id}:
                raise ValueError("Legacy job is already bound to a different Runtime run")
            if current is None:
                now = _now()
                connection.execute(
                    "UPDATE jobs SET runtime_run_id = ?, updated_at = ? WHERE id = ?",
                    (runtime_run_id, now, job_id),
                )
                self._event(connection, job_id, "runtime_bound", {"runtime_run_id": runtime_run_id})
        return self.get(job_id)

    def project_runtime(self, job_id: str, runtime_view: dict) -> Job:
        """Copy a terminal Runtime fact into the legacy read model.

        ``runtime_view`` is retained as a pointer-rich snapshot for old clients;
        RuntimeStore remains the source of truth for attempts, artifacts and
        canonical terminal status.
        """
        run = runtime_view.get("run") if isinstance(runtime_view, dict) else None
        if not isinstance(run, dict):
            raise ValueError("runtime_view requires a run object")
        runtime_run_id = run.get("run_id")
        try:
            runtime_status = RuntimeStatus(run.get("status"))
        except ValueError as exc:
            raise ValueError("runtime_view has an invalid Runtime status") from exc
        if runtime_status not in {
            RuntimeStatus.SUCCEEDED, RuntimeStatus.FAILED, RuntimeStatus.CANCELLED,
            RuntimeStatus.TIMED_OUT, RuntimeStatus.LOST,
        }:
            raise ValueError("Only a terminal Runtime run may be projected")
        legacy_status = {
            RuntimeStatus.SUCCEEDED: RunStatus.SUCCEEDED,
            RuntimeStatus.CANCELLED: RunStatus.CANCELLED,
            RuntimeStatus.FAILED: RunStatus.FAILED,
            RuntimeStatus.TIMED_OUT: RunStatus.FAILED,
            RuntimeStatus.LOST: RunStatus.FAILED,
        }[runtime_status]
        error = _runtime_projection_error(runtime_view) if legacy_status is RunStatus.FAILED else None
        now = _now()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT runtime_run_id FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown job: {job_id}")
            if row["runtime_run_id"] != runtime_run_id:
                raise ValueError("Runtime projection does not match the job binding")
            connection.execute(
                """UPDATE jobs SET status = ?, result_json = ?, error = ?, updated_at = ?
                   WHERE id = ?""",
                (legacy_status.value, json.dumps(runtime_view, ensure_ascii=False),
                 error, now, job_id),
            )
            self._event(connection, job_id, "runtime_projected", {
                "runtime_run_id": runtime_run_id,
                "runtime_status": runtime_status.value,
                "legacy_status": legacy_status.value,
            })
        return self.get(job_id)

    def heartbeat(self, job_id: str) -> None:
        now = _now()
        with self._connect() as connection:
            connection.execute(
                "UPDATE jobs SET heartbeat_at = ?, updated_at = ? WHERE id = ?",
                (now, now, job_id),
            )

    def record_stage(self, job_id: str, payload: dict) -> None:
        with self._connect() as connection:
            self._event(connection, job_id, "stage_completed", payload)

    def request_cancel(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.status == RunStatus.QUEUED:
            self._transition(job_id, {RunStatus.QUEUED}, RunStatus.CANCELLED, "cancelled")
        elif job.status in {RunStatus.PREPARING, RunStatus.RUNNING}:
            self._transition(
                job_id,
                {RunStatus.PREPARING, RunStatus.RUNNING},
                RunStatus.CANCEL_REQUESTED,
                "cancel_requested",
            )
        return self.get(job_id)

    def mark_cancelled(self, job_id: str) -> None:
        self._transition(
            job_id,
            {RunStatus.PREPARING, RunStatus.CANCEL_REQUESTED},
            RunStatus.CANCELLED,
            "cancelled",
        )

    def cancel_requested(self, job_id: str) -> bool:
        return self.get(job_id).status in {RunStatus.CANCEL_REQUESTED, RunStatus.CANCELLED}

    def complete(self, job_id: str, result: RunResult) -> None:
        if result.status not in TERMINAL:
            raise ValueError(f"Cannot complete a job with status {result.status.value}")
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """UPDATE jobs SET status = ?, result_json = ?, error = ?, updated_at = ?
                   WHERE id = ?""",
                (result.status.value, json.dumps(result.to_dict(), ensure_ascii=False),
                 result.error, now, job_id),
            )
            self._event(connection, job_id, "completed", {"status": result.status.value})

    def fail(self, job_id: str, error: str) -> None:
        now = _now()
        with self._connect() as connection:
            connection.execute(
                "UPDATE jobs SET status = ?, error = ?, updated_at = ? WHERE id = ?",
                (RunStatus.FAILED.value, error, now, job_id),
            )
            self._event(connection, job_id, "failed", {"error": error})

    def events(self, job_id: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT kind, payload_json, created_at FROM job_events WHERE job_id = ? ORDER BY id",
                (job_id,),
            ).fetchall()
        return [{"kind": row["kind"], "payload": json.loads(row["payload_json"]),
                 "created_at": row["created_at"]} for row in rows]

    def _transition(
        self,
        job_id: str,
        allowed: set[RunStatus],
        target: RunStatus,
        event: str,
    ) -> None:
        now = _now()
        placeholders = ",".join("?" for _ in allowed)
        values = [target.value, now, job_id, *(item.value for item in allowed)]
        with self._connect() as connection:
            changed = connection.execute(
                f"UPDATE jobs SET status = ?, updated_at = ? WHERE id = ? "
                f"AND status IN ({placeholders})",
                values,
            )
            if changed.rowcount != 1:
                current = connection.execute(
                    "SELECT status FROM jobs WHERE id = ?", (job_id,)
                ).fetchone()
                value = current["status"] if current else "missing"
                raise ValueError(f"Invalid job transition {value} -> {target.value}")
            self._event(connection, job_id, event, {})

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    result_json TEXT,
                    error TEXT,
                    claimed_by TEXT,
                    heartbeat_at TEXT,
                    runtime_run_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_status_created
                    ON jobs(status, created_at);
                CREATE TABLE IF NOT EXISTS job_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(id),
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
            }
            if "runtime_run_id" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN runtime_run_id TEXT")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _event(connection: sqlite3.Connection, job_id: str, kind: str, payload: dict) -> None:
        connection.execute(
            """INSERT INTO job_events (job_id, kind, payload_json, created_at)
               VALUES (?, ?, ?, ?)""",
            (job_id, kind, json.dumps(payload, ensure_ascii=False), _now()),
        )

    @staticmethod
    def _job(row: sqlite3.Row) -> Job:
        return Job(
            id=row["id"],
            status=RunStatus(row["status"]),
            request=RunRequest.from_dict(json.loads(row["request_json"])),
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            error=row["error"],
            runtime_run_id=row["runtime_run_id"],
            claimed_by=row["claimed_by"],
            heartbeat_at=row["heartbeat_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _runtime_projection_error(runtime_view: dict) -> str:
    run = runtime_view["run"]
    reason = str(run.get("terminal_reason") or run.get("status") or "runtime_failed")
    for stage in runtime_view.get("stages", []):
        for attempt in reversed(stage.get("attempts", [])):
            failure = attempt.get("failure")
            if isinstance(failure, dict) and failure.get("message"):
                return f"{reason}: {failure['message']}"
    return reason
