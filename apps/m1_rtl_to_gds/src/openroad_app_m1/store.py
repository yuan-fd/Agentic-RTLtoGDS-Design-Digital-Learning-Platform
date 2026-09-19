"""Small M1-owned state store; it never opens the v2 database."""

from __future__ import annotations

import sqlite3
from .models import M1Session, RTLVersion


class M1Store:
    def __init__(self, database: str = ":memory:") -> None:
        self.connection = sqlite3.connect(database)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS m1_sessions "
            "(spec_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS m1_rtl_versions "
            "(version_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
        self.connection.commit()

    def put_session(self, session: M1Session, payload: str) -> None:
        session.validate()
        self.connection.execute(
            "INSERT OR REPLACE INTO m1_sessions(spec_id, payload) VALUES (?, ?)",
            (session.spec_id, payload),
        )
        self.connection.commit()

    def put_version(self, version: RTLVersion, payload: str) -> None:
        version.validate()
        self.connection.execute(
            "INSERT OR REPLACE INTO m1_rtl_versions(version_id, payload) VALUES (?, ?)",
            (version.version_id, payload),
        )
        self.connection.commit()

    def session_payload(self, spec_id: str) -> str:
        row = self.connection.execute(
            "SELECT payload FROM m1_sessions WHERE spec_id = ?", (spec_id,)
        ).fetchone()
        if row is None:
            raise KeyError(spec_id)
        return str(row["payload"])

    def version_payload(self, version_id: str) -> str:
        row = self.connection.execute(
            "SELECT payload FROM m1_rtl_versions WHERE version_id = ?", (version_id,)
        ).fetchone()
        if row is None:
            raise KeyError(version_id)
        return str(row["payload"])

    def all_session_payloads(self) -> tuple[str, ...]:
        rows = self.connection.execute("SELECT payload FROM m1_sessions ORDER BY spec_id").fetchall()
        return tuple(str(row["payload"]) for row in rows)

    def all_version_payloads(self) -> tuple[str, ...]:
        rows = self.connection.execute(
            "SELECT payload FROM m1_rtl_versions ORDER BY version_id"
        ).fetchall()
        return tuple(str(row["payload"]) for row in rows)

    def close(self) -> None:
        self.connection.close()
