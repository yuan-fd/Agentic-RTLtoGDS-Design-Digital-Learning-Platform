"""Durable append-only store for L1 audit trace events."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from openroad_platform_contracts.l1_trace import L1TraceEvent


def _canonical(event: L1TraceEvent) -> str:
    return json.dumps(event.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _digest(serialized: str, previous_event_sha256: str | None = None) -> str:
    """Return an event digest bound to its predecessor.

    The predecessor digest is storage metadata rather than a planner-controlled
    contract field.  This makes a trace tamper-evident without allowing an LLM
    or plugin to choose its own chain link.
    """
    predecessor = previous_event_sha256 or ""
    return hashlib.sha256((predecessor + "\n" + serialized).encode("utf-8")).hexdigest()


class L1TraceStore:
    """Trace storage only; Runtime remains the authority for execution facts."""

    def __init__(self, database: str | Path) -> None:
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS l1_trace_event (
                    trace_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    parent_event_id TEXT,
                    event_json TEXT NOT NULL,
                    previous_event_sha256 TEXT,
                    event_sha256 TEXT NOT NULL,
                    PRIMARY KEY(trace_id, event_id),
                    UNIQUE(trace_id, sequence)
                )"""
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(l1_trace_event)")}
            if "previous_event_sha256" not in columns:
                connection.execute("ALTER TABLE l1_trace_event ADD COLUMN previous_event_sha256 TEXT")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        return connection

    def append(self, event: L1TraceEvent) -> str:
        event.validate()
        payload = _canonical(event)
        with self._connect() as connection:
            last = connection.execute(
                "SELECT event_id, sequence, event_sha256 FROM l1_trace_event WHERE trace_id = ? ORDER BY sequence DESC LIMIT 1",
                (event.trace_id,),
            ).fetchone()
            if last is None:
                if event.sequence != 0 or event.parent_event_id is not None:
                    raise ValueError("first trace event must be sequence zero without a parent")
            else:
                if event.sequence != last["sequence"] + 1:
                    raise ValueError("trace event sequence is not append-only")
                if event.parent_event_id != last["event_id"]:
                    raise ValueError("trace event parent does not match previous event")
            predecessor = last["event_sha256"] if last is not None else None
            digest = _digest(payload, predecessor)
            try:
                connection.execute(
                    "INSERT INTO l1_trace_event(trace_id,event_id,sequence,parent_event_id,event_json,previous_event_sha256,event_sha256) VALUES(?,?,?,?,?,?,?)",
                    (event.trace_id, event.event_id, event.sequence, event.parent_event_id, payload, predecessor, digest),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("trace event identity or sequence already exists") from exc
        return digest

    def read(self, trace_id: str) -> tuple[L1TraceEvent, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT event_id, sequence, parent_event_id, event_json, previous_event_sha256, event_sha256 FROM l1_trace_event WHERE trace_id = ? ORDER BY sequence",
                (trace_id,),
            ).fetchall()
        result: list[L1TraceEvent] = []
        previous: L1TraceEvent | None = None
        previous_digest: str | None = None
        for expected_sequence, row in enumerate(rows):
            if row["sequence"] != expected_sequence:
                raise ValueError("stored L1 trace event sequence is not contiguous")
            if row["parent_event_id"] != (previous.event_id if previous else None):
                raise ValueError("stored L1 trace event parent does not match predecessor")
            if row["previous_event_sha256"] != previous_digest:
                raise ValueError("stored L1 trace event predecessor digest mismatch")
            if _digest(row["event_json"], previous_digest) != row["event_sha256"]:
                raise ValueError("stored L1 trace event digest mismatch")
            event = L1TraceEvent.from_dict(json.loads(row["event_json"]))
            if event.event_id != row["event_id"] or event.sequence != row["sequence"] or event.parent_event_id != row["parent_event_id"]:
                raise ValueError("stored L1 trace event columns disagree with payload")
            result.append(event)
            previous = event
            previous_digest = row["event_sha256"]
        return tuple(result)
