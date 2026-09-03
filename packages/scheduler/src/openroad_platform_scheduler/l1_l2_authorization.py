"""Narrow, evidence-gated L1-to-L2 escalation; never an optimizer."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Iterable

from openroad_platform_contracts.agent_control import DesignGoal, DesignState
from openroad_platform_contracts.l1_trace import TraceEventKind
from openroad_platform_contracts.l2_optimization import L2HandoffAuthorization
from openroad_platform_contracts.learning import EvidencePointer


def _digest(value: object) -> str:
    payload = value.to_dict() if hasattr(value, "to_dict") else value
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class L1L2AuthorizationService:
    """Turn a durable ``escalate`` reflection into one typed receipt.

    There is deliberately no automatic escalation: a stop/continue reflection
    cannot pass this gate, nor can a lone baseline result.
    """
    trace: object

    def authorize(self, trace_id: str, goal: DesignGoal, state: DesignState) -> L2HandoffAuthorization:
        goal.validate(); state.validate()
        if state.status != "observed" or not state.evidence:
            raise ValueError("L2 upgrade requires an evidence-backed observed L1 state")
        events = tuple(self.trace.store.read(trace_id))
        finalized = [event for event in events if event.kind is TraceEventKind.GOAL_FINALIZED and event.goal_id == goal.goal_id]
        if len(finalized) != 1:
            raise ValueError("L2 upgrade requires exactly one frozen Goal IR")
        transitions = [event for event in events if event.kind is TraceEventKind.STATE_TRANSITION
                       and event.goal_id == goal.goal_id and event.facts.get("terminal_status") == "succeeded"]
        run_ids = [str(event.facts.get("run_id")) for event in transitions if event.facts.get("run_id")]
        if len(set(run_ids)) < 2:
            raise ValueError("L2 upgrade requires distinct measured baseline and candidate Runtime observations")
        reflections = [event for event in events if event.kind is TraceEventKind.REFLECTION_RECORDED
                       and event.goal_id == goal.goal_id]
        if not reflections or reflections[-1].facts.get("decision") != "escalate":
            raise ValueError("L2 upgrade requires an explicit durable escalate reflection")
        reflection = reflections[-1]
        basis = set(reflection.facts.get("basis_event_ids") or ())
        transition_ids = {event.event_id for event in transitions}
        if not basis & transition_ids:
            raise ValueError("L2 escalate reflection must cite measured Runtime evidence")
        # The newest state must itself be a Runtime state in this trace.  This
        # prevents an authorization against an unrelated stale observation.
        state_events = [event for event in transitions if event.state_after_sha256]
        if not state_events or state_events[-1].state_after_sha256 != _digest(state):
            raise ValueError("L2 upgrade state is not the latest measured Runtime state")
        baseline, candidate = run_ids[0], run_ids[-1]
        evidence = tuple(dict.fromkeys((*state.evidence, *reflection.evidence)))
        auth = L2HandoffAuthorization(
            authorization_id=f"l2-auth-{_digest({'trace': trace_id, 'state': state.state_id, 'reflection': reflection.event_id})[:24]}",
            l1_trace_id=trace_id, goal_id=goal.goal_id, source_state_id=state.state_id,
            reflection_event_id=reflection.event_id, baseline_run_id=baseline,
            candidate_run_id=candidate, evidence=evidence,
        )
        auth.validate()
        prior = [event for event in events if event.kind is TraceEventKind.L2_HANDOFF_AUTHORIZED
                 and event.facts.get("authorization_id") == auth.authorization_id]
        if prior:
            if len(prior) != 1:
                raise ValueError("duplicate L2 authorization receipt")
            return auth
        self.trace.record_l2_handoff_authorization(trace_id, state,
            authorization={"handoff_id": auth.authorization_id, "l1_trace_id": auth.l1_trace_id,
                           "goal_id": auth.goal_id, "source_state_id": auth.source_state_id,
                           "reflection_event_id": auth.reflection_event_id,
                           "baseline_run_id": auth.baseline_run_id, "candidate_run_id": auth.candidate_run_id,
                           "claim_boundary": "bounded external optimizer admission; no QoR improvement claim"},
            evidence=auth.evidence)
        return auth
