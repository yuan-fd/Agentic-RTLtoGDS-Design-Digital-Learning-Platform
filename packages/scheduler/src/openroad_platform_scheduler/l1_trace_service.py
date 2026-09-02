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
from openroad_platform_contracts.l1_policy import TrustedPolicyIdentity
from openroad_platform_contracts.l1_trace import L1TraceEvent, TraceEventKind

from .l1_trace_store import L1TraceStore
from .l1_state_reducer import L1StateReducer


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

    def _require_current_state(self, trace_id: str, state: DesignState) -> None:
        """Keep a trace linear: stateful events must extend its latest state."""
        state.validate()
        prior = next((event for event in reversed(self.store.read(trace_id))
                      if event.state_after_sha256 is not None), None)
        if prior is not None and prior.state_after_sha256 != _hash(state):
            raise ValueError("stateful trace event uses a stale or forked DesignState")

    def _require_call_history(self, trace_id: str, state: DesignState, call: SemanticToolCall,
                              *, require_allowed_policy: bool) -> None:
        events = self.store.read(trace_id)
        called = any(event.kind is TraceEventKind.TOOL_CALLED and event.goal_id == state.goal_id
                     and event.tool is call.tool and event.facts.get("call_id") == call.call_id
                     and event.state_before_sha256 == _hash(state) for event in events)
        if not called:
            raise ValueError("trace event requires a prior matching tool call")
        if require_allowed_policy and not any(
            event.kind is TraceEventKind.POLICY_DECIDED and event.goal_id == state.goal_id
            and event.tool is call.tool and event.facts.get("call_id") == call.call_id
            and event.policy_verdict == "allow" and event.state_before_sha256 == _hash(state)
            for event in events
        ):
            raise ValueError("tool receipt requires a prior matching allowed policy")

    def record_draft(self, trace_id: str, draft: GoalDraft) -> L1TraceEvent:
        draft.validate()
        return self._append(trace_id, kind=TraceEventKind.GOAL_DRAFTED, goal_id=draft.draft_id,
                            facts={"request_sha256": draft.request_sha256, "intent": draft.intent.value,
                                   "blocking_fields": [item.value for item in draft.unresolved_blocking_fields()]})

    def record_goal(self, trace_id: str, goal: DesignGoal) -> L1TraceEvent:
        goal.validate()
        policy_anchor = {key: goal.labels[key] for key in (
            "l1_policy_id", "l1_policy_version", "l1_policy_issuer",
            "l1_policy_provenance", "l1_policy_provenance_sha256",
        ) if key in goal.labels}
        return self._append(trace_id, kind=TraceEventKind.GOAL_FINALIZED, goal_id=goal.goal_id,
                            facts={"goal_sha256": _hash(goal), "toolchain_id": goal.toolchain_id,
                                   "pdk_id": goal.pdk_id, "allowed_tools": [item.value for item in goal.allowed_tools],
                                   "policy_anchor": policy_anchor},
                            evidence=(goal.rtl_artifact,))

    def record_call(self, trace_id: str, state: DesignState, call: SemanticToolCall,
                    *, planner_summary: str, hypotheses: dict | None = None) -> L1TraceEvent:
        state.validate(); call.validate()
        self._require_current_state(trace_id, state)
        if call.goal_id != state.goal_id or call.state_id != state.state_id:
            raise ValueError("tool call does not match trace state")
        return self._append(trace_id, kind=TraceEventKind.TOOL_CALLED, goal_id=state.goal_id,
                            state_before=state, state_after=state, planner_summary=planner_summary,
                            tool=call.tool, facts={"call_id": call.call_id, "arguments": call.arguments,
                                                   "producer": call.producer}, hypotheses=hypotheses,
                            evidence=call.evidence)

    def record_policy(self, trace_id: str, goal: DesignGoal, state: DesignState, call: SemanticToolCall,
                      policy: TrustedPolicyIdentity, *, verdict: str, summary: str) -> L1TraceEvent:
        goal.validate(); state.validate(); call.validate(); policy.validate()
        self._require_current_state(trace_id, state)
        if state.goal_id != goal.goal_id or call.goal_id != state.goal_id or call.state_id != state.state_id:
            raise ValueError("policy call does not match trace state")
        expected = {"l1_policy_id": policy.policy_id, "l1_policy_version": policy.policy_version,
                    "l1_policy_issuer": policy.issuer, "l1_policy_provenance": policy.provenance.ref,
                    "l1_policy_provenance_sha256": policy.provenance.sha256}
        if any(goal.labels.get(key) != value for key, value in expected.items()):
            raise ValueError("policy identity does not match the finalized DesignGoal")
        finalized = [event for event in self.store.read(trace_id)
                     if event.kind is TraceEventKind.GOAL_FINALIZED and event.goal_id == goal.goal_id]
        if len(finalized) != 1:
            raise ValueError("policy decision requires exactly one finalized Goal trace anchor")
        anchor = finalized[0].facts
        if anchor.get("goal_sha256") != _hash(goal) or anchor.get("policy_anchor") != expected:
            raise ValueError("policy decision does not match the durable finalized Goal anchor")
        self._require_call_history(trace_id, state, call, require_allowed_policy=False)
        if verdict not in {"allow", "deny", "needs_clarification"}:
            raise ValueError("trace policy verdict is unsupported")
        return self._append(trace_id, kind=TraceEventKind.POLICY_DECIDED, goal_id=state.goal_id,
                            state_before=state, state_after=state, planner_summary=summary, tool=call.tool,
                            policy_verdict=verdict, facts={"call_id": call.call_id, "policy": policy.to_dict()},
                            evidence=(*call.evidence, policy.provenance))

    def record_receipt(self, trace_id: str, state: DesignState, receipt: ToolReceipt) -> L1TraceEvent:
        receipt.validate()
        self._require_current_state(trace_id, state)
        if receipt.goal_id != state.goal_id or receipt.state_id != state.state_id:
            raise ValueError("tool receipt does not match trace state")
        call = SemanticToolCall(receipt.call_id, receipt.goal_id, receipt.state_id, receipt.tool, {}, "receipt-link")
        self._require_call_history(trace_id, state, call, require_allowed_policy=True)
        return self._append(trace_id, kind=TraceEventKind.TOOL_RECEIPT, goal_id=state.goal_id,
                            state_before=state, state_after=state, tool=receipt.tool,
                            facts={"call_id": receipt.call_id, "status": receipt.status, "result": receipt.result},
                            evidence=receipt.evidence)

    def record_observation(self, trace_id: str, before: DesignState, after: DesignState,
                           observation: RuntimeObservation) -> L1TraceEvent:
        before.validate(); after.validate()
        observation.validate()
        self._require_current_state(trace_id, before)
        if after.parent_state_id != before.state_id or after.goal_id != before.goal_id:
            raise ValueError("observation state lineage is invalid")
        expected = L1StateReducer.apply(before, observation, next_state_id=after.state_id)
        if after != expected:
            raise ValueError("observation successor state is not the canonical reducer result")
        existing = self.store.read(trace_id)
        previous = existing[-1] if existing else None
        event = L1TraceEvent(
            trace_id=trace_id, event_id=f"trace-event-{uuid4().hex}", sequence=len(existing),
            kind=TraceEventKind.STATE_TRANSITION, goal_id=before.goal_id, occurred_at=self.clock().isoformat(),
            state_before_sha256=_hash(before), state_after_sha256=_hash(after), planner_summary=None,
            tool=None, policy_verdict=None, facts={"run_id": observation.run_id,
            "attempt_id": observation.attempt_id, "terminal_status": observation.terminal_status,
            "metrics": observation.metrics}, hypotheses={}, evidence=observation.evidence,
            parent_event_id=previous.event_id if previous else None,
        )
        self.store.append_state_transition(event, before=before, after=after, observation=observation)
        return event

    def record_stopped(self, trace_id: str, state: DesignState, *, run_id: str, reason: str) -> L1TraceEvent:
        """Record the terminal cancellation fact after Runtime observation.

        This is not a model conclusion: it is a durable projection of the
        Runtime terminal fact and the typed user/agent stop reason.
        """
        if state.status != "stopped":
            raise ValueError("STOPPED trace fact requires a cancelled Runtime successor")
        if not isinstance(run_id, str) or not run_id or not isinstance(reason, str) or not reason.strip():
            raise ValueError("stopped trace fact is invalid")
        self._require_current_state(trace_id, state)
        return self._append(trace_id, kind=TraceEventKind.STOPPED, goal_id=state.goal_id,
                            state_before=state, state_after=state,
                            facts={"run_id": run_id, "reason": reason}, evidence=state.evidence)
