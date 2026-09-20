"""Small M1-owned state store; it never opens the v2 database."""

from __future__ import annotations

import sqlite3
import threading
from .models import M1RunOutcome, M1Session, RTLVersion
from openroad_platform_contracts.rtl_frontend import VerificationPackage
from openroad_platform_contracts.evidence_exchange import EvidenceRef


class M1Store:
    def __init__(self, database: str = ":memory:") -> None:
        self._lock = threading.RLock()
        self.connection = sqlite3.connect(database, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS m1_sessions "
            "(spec_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS m1_rtl_versions "
            "(version_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS m1_verification_packages "
            "(spec_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS m1_evidence "
            "(evidence_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS m1_run_owners "
            "(run_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL)"
        )
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS m1_run_outcomes "
            "(run_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
        self.connection.commit()

    def put_session(self, session: M1Session, payload: str) -> None:
        session.validate()
        with self._lock:
            self.connection.execute(
                "INSERT OR REPLACE INTO m1_sessions(spec_id, payload) VALUES (?, ?)",
                (session.spec_id, payload),
            )
            self.connection.commit()

    def put_version(self, version: RTLVersion, payload: str) -> None:
        version.validate()
        with self._lock:
            self.connection.execute(
                "INSERT OR REPLACE INTO m1_rtl_versions(version_id, payload) VALUES (?, ?)",
                (version.version_id, payload),
            )
            self.connection.commit()

    def put_verification_package(self, package: VerificationPackage, payload: str) -> None:
        package.validate()
        with self._lock:
            self.connection.execute(
                "INSERT OR REPLACE INTO m1_verification_packages(spec_id, payload) VALUES (?, ?)",
                (package.spec_id, payload),
            )
            self.connection.commit()

    def put_evidence(self, evidence: EvidenceRef, payload: str) -> None:
        evidence.validate()
        with self._lock:
            self.connection.execute(
                "INSERT OR REPLACE INTO m1_evidence(evidence_id, payload) VALUES (?, ?)",
                (evidence.evidence_id, payload),
            )
            self.connection.commit()

    def put_run_owner(self, run_id: str, owner_id: str) -> None:
        with self._lock:
            self.connection.execute(
                "INSERT OR REPLACE INTO m1_run_owners(run_id, owner_id) VALUES (?, ?)",
                (run_id, owner_id),
            )
            self.connection.commit()

    def run_owner(self, run_id: str) -> str | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT owner_id FROM m1_run_owners WHERE run_id = ?", (run_id,)
            ).fetchone()
        return None if row is None else str(row["owner_id"])

    def put_run_outcome(self, outcome: M1RunOutcome, payload: str) -> None:
        outcome.validate()
        with self._lock:
            self.connection.execute(
                "INSERT OR REPLACE INTO m1_run_outcomes(run_id, payload) VALUES (?, ?)",
                (outcome.run_id, payload),
            )
            self.connection.commit()

    def run_outcome_payload(self, run_id: str) -> str:
        with self._lock:
            row = self.connection.execute(
                "SELECT payload FROM m1_run_outcomes WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return str(row["payload"])

    def all_run_outcome_payloads(self) -> tuple[str, ...]:
        with self._lock:
            rows = self.connection.execute(
                "SELECT payload FROM m1_run_outcomes ORDER BY run_id"
            ).fetchall()
        return tuple(str(row["payload"]) for row in rows)

    def session_payload(self, spec_id: str) -> str:
        with self._lock:
            row = self.connection.execute(
                "SELECT payload FROM m1_sessions WHERE spec_id = ?", (spec_id,)
            ).fetchone()
        if row is None:
            raise KeyError(spec_id)
        return str(row["payload"])

    def version_payload(self, version_id: str) -> str:
        with self._lock:
            row = self.connection.execute(
                "SELECT payload FROM m1_rtl_versions WHERE version_id = ?", (version_id,)
            ).fetchone()
        if row is None:
            raise KeyError(version_id)
        return str(row["payload"])

    def all_session_payloads(self) -> tuple[str, ...]:
        with self._lock:
            rows = self.connection.execute("SELECT payload FROM m1_sessions ORDER BY spec_id").fetchall()
        return tuple(str(row["payload"]) for row in rows)

    def all_version_payloads(self) -> tuple[str, ...]:
        with self._lock:
            rows = self.connection.execute(
                "SELECT payload FROM m1_rtl_versions ORDER BY version_id"
            ).fetchall()
        return tuple(str(row["payload"]) for row in rows)

    def all_verification_package_payloads(self) -> tuple[str, ...]:
        with self._lock:
            rows = self.connection.execute(
                "SELECT payload FROM m1_verification_packages ORDER BY spec_id"
            ).fetchall()
        return tuple(str(row["payload"]) for row in rows)

    def all_evidence_payloads(self) -> tuple[str, ...]:
        with self._lock:
            rows = self.connection.execute(
                "SELECT payload FROM m1_evidence ORDER BY evidence_id"
            ).fetchall()
        return tuple(str(row["payload"]) for row in rows)

    def close(self) -> None:
        with self._lock:
            self.connection.close()
