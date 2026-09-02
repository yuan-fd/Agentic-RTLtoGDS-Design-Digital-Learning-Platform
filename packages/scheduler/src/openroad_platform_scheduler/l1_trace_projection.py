"""Read-only presentation projection for durable L1 traces."""
from __future__ import annotations

from .l1_trace_store import L1TraceStore


def list_trace_ids(store: L1TraceStore) -> tuple[str, ...]:
    with store._connect() as connection:  # read-only discovery; store validates event reads.
        rows = connection.execute("SELECT DISTINCT trace_id FROM l1_trace_event ORDER BY trace_id").fetchall()
    return tuple(row[0] for row in rows)


def project_trace(store: L1TraceStore, trace_id: str) -> dict:
    """Return durable stored facts; never fabricate an agent narrative."""
    events = store.read(trace_id)
    if not events:
        raise KeyError(trace_id)
    return {"trace_id": trace_id, "event_count": len(events), "events": [
        {"sequence": item.sequence, "event_id": item.event_id, "occurred_at": item.occurred_at,
         "kind": item.kind.value, "goal_id": item.goal_id,
         "tool": item.tool.value if item.tool else None, "policy_verdict": item.policy_verdict,
         "planner_summary": item.planner_summary, "facts": item.facts,
         "hypotheses": item.hypotheses,
         "evidence": [pointer.to_dict() for pointer in item.evidence],
         "state_before_sha256": item.state_before_sha256,
         "state_after_sha256": item.state_after_sha256}
        for item in events]}
