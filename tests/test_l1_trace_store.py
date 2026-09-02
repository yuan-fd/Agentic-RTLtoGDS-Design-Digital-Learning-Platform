from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from openroad_platform_contracts.agent_control import ToolName
from openroad_platform_contracts.l1_trace import L1TraceEvent, TraceEventKind
from openroad_platform_contracts.learning import EvidencePointer
from openroad_platform_scheduler.l1_trace_store import L1TraceStore


def _event(sequence: int, parent: str | None) -> L1TraceEvent:
    return L1TraceEvent(
        trace_id="trace-1", event_id=f"event-{sequence}", sequence=sequence,
        parent_event_id=parent, kind=TraceEventKind.TOOL_RECEIPT, goal_id="goal-1",
        occurred_at="2026-09-02T12:00:00+00:00", state_before_sha256=("a" if sequence == 0 else "b") * 64,
        state_after_sha256="b" * 64, planner_summary="Read verified timing.",
        tool=ToolName.QUERY_TIMING, policy_verdict="allow", facts={"wns": -0.1},
        hypotheses={}, evidence=(EvidencePointer("artifact:timing", "c" * 64),),
    )


def test_store_appends_and_replays_hash_verified_trace(tmp_path: Path) -> None:
    store = L1TraceStore(tmp_path / "trace.sqlite")
    first, second = _event(0, None), _event(1, "event-0")
    assert len(store.append(first)) == 64
    store.append(second)
    assert store.read("trace-1") == (first, second)


def test_store_rejects_non_append_and_tampered_event(tmp_path: Path) -> None:
    database = tmp_path / "trace.sqlite"; store = L1TraceStore(database)
    store.append(_event(0, None))
    with pytest.raises(ValueError, match="sequence"):
        store.append(_event(2, "event-0"))
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE l1_trace_event SET event_json = ?", ("{}",))
    with pytest.raises(ValueError, match="digest mismatch"):
        store.read("trace-1")


def test_store_rejects_state_hash_discontinuity(tmp_path: Path) -> None:
    store = L1TraceStore(tmp_path / "trace.sqlite")
    store.append(_event(0, None))
    broken = L1TraceEvent(**{**_event(1, "event-0").__dict__, "state_before_sha256": "c" * 64})
    with pytest.raises(ValueError, match="state does not continue"):
        store.append(broken)


@pytest.mark.parametrize("column", ["event_json", "parent_event_id", "sequence"])
def test_store_rejects_rehashed_or_relinked_history(tmp_path: Path, column: str) -> None:
    database = tmp_path / "trace.sqlite"; store = L1TraceStore(database)
    store.append(_event(0, None)); store.append(_event(1, "event-0"))
    with sqlite3.connect(database) as connection:
        if column == "event_json":
            replacement = _event(0, None).to_dict(); replacement["facts"] = {"wns": 99.0}
            payload = json.dumps(replacement, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            digest = hashlib.sha256(("\n" + payload).encode("utf-8")).hexdigest()
            connection.execute("UPDATE l1_trace_event SET event_json=?, event_sha256=? WHERE sequence=0", (payload, digest))
        elif column == "parent_event_id":
            connection.execute("UPDATE l1_trace_event SET parent_event_id=? WHERE sequence=1", ("wrong-parent",))
        else:
            connection.execute("UPDATE l1_trace_event SET sequence=? WHERE sequence=1", (7,))
    with pytest.raises(ValueError):
        store.read("trace-1")
