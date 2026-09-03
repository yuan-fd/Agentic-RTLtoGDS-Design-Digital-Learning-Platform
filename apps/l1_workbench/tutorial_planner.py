"""A deterministic, evidence-only planner for the managed L1 tutorial.

It is intentionally not an optimizer and never owns Runtime.  The small
teaching policy makes every next action inspectable; a future structured LLM
may propose an action, but must be checked against the same Goal/Policy path.
"""
from __future__ import annotations

from dataclasses import dataclass

from openroad_platform_contracts.agent_control import DesignGoal, DesignState


@dataclass(frozen=True)
class TutorialDecision:
    action: str
    summary: str
    hypothesis: dict[str, str]
    basis_event_ids: tuple[str, ...]


class TutorialEvidencePlanner:
    """Select a bounded baseline → timing → route → DRC teaching loop."""

    @staticmethod
    def choose(goal: DesignGoal, state: DesignState, events: list[dict]) -> TutorialDecision:
        goal.validate(); state.validate()
        relevant = [event for event in events if event.get("goal_id") == goal.goal_id]
        ids = tuple(event["event_id"] for event in relevant if event.get("event_id"))
        tools = [event.get("tool") for event in relevant if event.get("kind") == "tool_receipt"]
        reflections = [event for event in relevant if event.get("kind") == "reflection_recorded"]
        if state.status in {"failed", "stopped"}:
            return TutorialDecision("stop", "Runtime reached a terminal non-success state; preserve evidence and stop.",
                                    {"reason": "runtime_terminal"}, ids[-1:])
        if state.remaining_budget.max_eda_runs == 0:
            return TutorialDecision("stop", "The frozen EDA-run budget is exhausted; return recorded evidence.",
                                    {"reason": "budget_exhausted"}, ids[-1:])
        if state.revision == 0:
            return TutorialDecision("run_full_flow", "No measured baseline exists; run the frozen full flow before proposing any change.",
                                    {"reason": "baseline_required"}, ids[-1:])
        if "query_timing" not in tools:
            return TutorialDecision("query_timing", "A Runtime observation exists; read typed timing facts before selecting a physical stage.",
                                    {"reason": "timing_evidence_required"}, ids[-1:])
        if state.revision == 1 and not any(item.get("facts", {}).get("decision") == "continue" for item in reflections):
            return TutorialDecision("reflect_continue", "Timing facts are recorded; run the permitted route stage to obtain an independent stage observation.",
                                    {"reason": "stage_observation_required"}, ids[-2:])
        if state.revision == 1:
            return TutorialDecision("run_route", "The policy permits route and budget remains; execute one selected route-stage Runtime transaction.",
                                    {"reason": "route_selected"}, ids[-1:])
        if "query_drc" not in tools:
            return TutorialDecision("query_drc", "Route observation exists; read typed DRC facts before declaring the Goal satisfied.",
                                    {"reason": "drc_evidence_required"}, ids[-1:])
        if "drc_errors" not in state.metrics:
            return TutorialDecision("stop", "No canonical DRC metric was produced by the current toolchain; do not claim closure.",
                                    {"reason": "missing_drc_evidence"}, ids[-2:])
        if state.metrics["drc_errors"] > 0:
            return TutorialDecision("stop", "Measured DRC violations remain; preserve the failure evidence and stop.",
                                    {"reason": "drc_violation"}, ids[-2:])
        return TutorialDecision("stop", "The bounded tutorial loop has observed its required evidence; stop without an unsupported optimization claim.",
                                {"reason": "tutorial_complete"}, ids[-2:])
