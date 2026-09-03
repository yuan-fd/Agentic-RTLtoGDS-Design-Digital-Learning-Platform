"""Durable append-only store for L1 audit trace events."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from openroad_platform_contracts.l1_trace import L1TraceEvent, TraceEventKind
from openroad_platform_contracts.l1_observation import RuntimeObservation

from .l1_state_reducer import L1StateReducer


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


def _digest_event(value: object) -> str:
    payload = value.to_dict() if hasattr(value, "to_dict") else value
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


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
        if event.kind is TraceEventKind.STATE_TRANSITION:
            raise ValueError("state transitions require the Runtime observation append boundary")
        return self._append(event)

    def append_state_transition(self, event: L1TraceEvent, *, before, after,
                                observation: RuntimeObservation, consume_eda_run: bool = False) -> str:
        if event.kind is not TraceEventKind.STATE_TRANSITION:
            raise ValueError("Runtime observation append boundary only accepts state transitions")
        expected = L1StateReducer.apply(before, observation, next_state_id=after.state_id,
                                        consume_eda_run=consume_eda_run)
        if after != expected:
            raise ValueError("state transition does not match canonical Runtime reducer result")
        if event.state_before_sha256 != _digest_event(before) or event.state_after_sha256 != _digest_event(after):
            raise ValueError("state transition hashes do not match Runtime reducer states")
        return self._append(event)

    def _append(self, event: L1TraceEvent) -> str:
        event.validate()
        payload = _canonical(event)
        with self._connect() as connection:
            last = connection.execute(
                "SELECT event_id, sequence, event_sha256, event_json FROM l1_trace_event WHERE trace_id = ? ORDER BY sequence DESC LIMIT 1",
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
                state_rows = connection.execute(
                    "SELECT event_json FROM l1_trace_event WHERE trace_id = ? ORDER BY sequence DESC",
                    (event.trace_id,),
                ).fetchall()
                predecessor_event = next((parsed for row in state_rows
                                          if (parsed := L1TraceEvent.from_dict(json.loads(row["event_json"]))).state_after_sha256 is not None), None)
                if event.state_before_sha256 is not None and predecessor_event is not None and event.state_before_sha256 != predecessor_event.state_after_sha256:
                    raise ValueError("trace event state does not continue predecessor state")
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
        previous_state: L1TraceEvent | None = None
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
            if previous_state is not None and event.state_before_sha256 is not None and event.state_before_sha256 != previous_state.state_after_sha256:
                raise ValueError("stored L1 trace event state does not continue predecessor state")
            result.append(event)
            previous = event
            if event.state_after_sha256 is not None:
                previous_state = event
            previous_digest = row["event_sha256"]
        return tuple(result)
