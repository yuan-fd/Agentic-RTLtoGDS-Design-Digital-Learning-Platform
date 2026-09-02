"""Write the canonical L1 audit trail without owning Runtime state."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

from openroad_platform_contracts.agent_control import DesignGoal, DesignState, SemanticToolCall, ToolReceipt
from openroad_platform_contracts.l1_goal_draft import GoalDraft
from openroad_platform_contracts.l1_observation import RuntimeObservation
from openroad_platform_contracts.l1_trace import L1TraceEvent, TraceEventKind

from .l1_trace_store import L1TraceStore


def _hash(value: object) -> str:
    payload = value.to_dict() if hasattr(value, "to_dict") else value
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class L1TraceService:
    def __init__(self, store: L1TraceStore, *, clock: Callable[[], datetime] | None = None) -> None:
        self.store = store
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _append(self, trace_id: str, *, kind: TraceEventKind, goal_id: str,
                state_before: DesignState | None = None, state_after: DesignState | None = None,
                planner_summary: str | None = None, tool=None, policy_verdict: str | None = None,
                facts: dict | None = None, hypotheses: dict | None = None, evidence=()) -> L1TraceEvent:
        existing = self.store.read(trace_id)
        previous = existing[-1] if existing else None
        event = L1TraceEvent(
            trace_id=trace_id, event_id=f"trace-event-{uuid4().hex}", sequence=len(existing), kind=kind,
            goal_id=goal_id, occurred_at=self.clock().isoformat(),
            state_before_sha256=_hash(state_before) if state_before else None,
            state_after_sha256=_hash(state_after) if state_after else None,
            planner_summary=planner_summary, tool=tool, policy_verdict=policy_verdict,
            facts=facts or {}, hypotheses=hypotheses or {}, evidence=tuple(evidence),
            parent_event_id=previous.event_id if previous else None,
        )
        self.store.append(event)
        return event

    def record_draft(self, trace_id: str, draft: GoalDraft) -> L1TraceEvent:
        draft.validate()
        return self._append(trace_id, kind=TraceEventKind.GOAL_DRAFTED, goal_id=draft.draft_id,
                            facts={"request_sha256": draft.request_sha256, "intent": draft.intent.value,
                                   "blocking_fields": [item.value for item in draft.unresolved_blocking_fields()]})

    def record_goal(self, trace_id: str, goal: DesignGoal) -> L1TraceEvent:
        goal.validate()
        return self._append(trace_id, kind=TraceEventKind.GOAL_FINALIZED, goal_id=goal.goal_id,
                            facts={"goal_sha256": _hash(goal), "toolchain_id": goal.toolchain_id,
                                   "pdk_id": goal.pdk_id, "allowed_tools": [item.value for item in goal.allowed_tools]},
                            evidence=(goal.rtl_artifact,))

    def record_call(self, trace_id: str, state: DesignState, call: SemanticToolCall,
                    *, planner_summary: str, hypotheses: dict | None = None) -> L1TraceEvent:
        state.validate(); call.validate()
        if call.goal_id != state.goal_id or call.state_id != state.state_id:
            raise ValueError("tool call does not match trace state")
        return self._append(trace_id, kind=TraceEventKind.TOOL_CALLED, goal_id=state.goal_id,
                            state_before=state, state_after=state, planner_summary=planner_summary,
                            tool=call.tool, facts={"call_id": call.call_id, "arguments": call.arguments,
                                                   "producer": call.producer}, hypotheses=hypotheses,
                            evidence=call.evidence)

    def record_policy(self, trace_id: str, state: DesignState, call: SemanticToolCall, *, verdict: str,
                      summary: str) -> L1TraceEvent:
        if verdict not in {"allow", "deny", "needs_clarification"}:
            raise ValueError("trace policy verdict is unsupported")
        return self._append(trace_id, kind=TraceEventKind.POLICY_DECIDED, goal_id=state.goal_id,
                            state_before=state, state_after=state, planner_summary=summary, tool=call.tool,
                            policy_verdict=verdict, facts={"call_id": call.call_id}, evidence=call.evidence)

    def record_receipt(self, trace_id: str, state: DesignState, receipt: ToolReceipt,
                       *, next_state: DesignState | None = None) -> L1TraceEvent:
        receipt.validate()
        if receipt.goal_id != state.goal_id or receipt.state_id != state.state_id:
            raise ValueError("tool receipt does not match trace state")
        return self._append(trace_id, kind=TraceEventKind.TOOL_RECEIPT, goal_id=state.goal_id,
                            state_before=state, state_after=next_state or state, tool=receipt.tool,
                            facts={"call_id": receipt.call_id, "status": receipt.status, "result": receipt.result},
                            evidence=receipt.evidence)

    def record_observation(self, trace_id: str, before: DesignState, after: DesignState,
                           observation: RuntimeObservation) -> L1TraceEvent:
        observation.validate()
        if after.parent_state_id != before.state_id or after.goal_id != before.goal_id:
            raise ValueError("observation state lineage is invalid")
        return self._append(trace_id, kind=TraceEventKind.STATE_TRANSITION, goal_id=before.goal_id,
                            state_before=before, state_after=after, facts={"run_id": observation.run_id,
                            "attempt_id": observation.attempt_id, "terminal_status": observation.terminal_status,
                            "metrics": observation.metrics}, evidence=observation.evidence)
