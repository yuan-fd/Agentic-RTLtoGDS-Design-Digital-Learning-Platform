from __future__ import annotations

from apps.l1_workbench.tutorial_planner import TutorialEvidencePlanner
from openroad_platform_contracts.agent_control import AgentBudget, DesignGoal, DesignState, GoalPreference, QoRConstraint, ToolName
from openroad_platform_contracts.learning import EvidencePointer


def _goal() -> DesignGoal:
    return DesignGoal("goal_1", "tutorial_mux", "mux_2to1", "nangate45", "nangate45", "orfs_2d",
                      EvidencePointer("artifact:rtl", "a" * 64), GoalPreference.PERFORMANCE,
                      (QoRConstraint("setup_wns_ns", ">=", 0), QoRConstraint("drc_errors", "<=", 0)),
                      ("route", "finish"), ("place_density",), AgentBudget(3, 4, 7200), DEFAULT_TOOLS,
                      labels={})


DEFAULT_TOOLS = (ToolName.QUERY_TIMING, ToolName.QUERY_DRC, ToolName.RUN_STAGE,
                 ToolName.RUN_FULL_FLOW, ToolName.STOP_OR_ESCALATE)


def _state(revision: int, budget: int, metrics=None) -> DesignState:
    return DesignState(f"state_{revision}", "goal_1", revision, "observed" if revision else "running", None,
                       metrics or {}, AgentBudget(budget, 4, 7200),
                       evidence=(EvidencePointer("artifact:report", "b" * 64),))


def _event(kind: str, *, tool=None, decision=None) -> dict:
    facts = {"decision": decision} if decision else {}
    return {"event_id": f"event_{kind}_{tool or decision or 'x'}", "kind": kind,
            "goal_id": "goal_1", "tool": tool, "facts": facts}


def test_planner_emits_a_visible_artifact_backed_teaching_sequence() -> None:
    goal = _goal()
    assert TutorialEvidencePlanner.choose(goal, _state(0, 3), []).action == "run_full_flow"
    observed = [_event("state_transition")]
    assert TutorialEvidencePlanner.choose(goal, _state(1, 2), observed).action == "query_timing"
    timing = [*observed, _event("tool_receipt", tool="query_timing")]
    assert TutorialEvidencePlanner.choose(goal, _state(1, 2), timing).action == "reflect_continue"
    continued = [*timing, _event("reflection_recorded", decision="continue")]
    assert TutorialEvidencePlanner.choose(goal, _state(1, 2), continued).action == "run_route"
    routed = [*continued, _event("state_transition")]
    assert TutorialEvidencePlanner.choose(goal, _state(2, 1), routed).action == "query_drc"
    queried = [*routed, _event("tool_receipt", tool="query_drc")]
    decision = TutorialEvidencePlanner.choose(goal, _state(2, 1), queried)
    assert decision.action == "stop" and decision.hypothesis["reason"] == "missing_drc_evidence"


def test_planner_never_claims_success_from_missing_drc_or_exhausted_budget() -> None:
    goal = _goal()
    assert TutorialEvidencePlanner.choose(goal, _state(2, 0), [_event("state_transition")]).hypothesis["reason"] == "budget_exhausted"
    decision = TutorialEvidencePlanner.choose(goal, _state(2, 1, {"drc_errors": 1}), [_event("state_transition"), _event("tool_receipt", tool="query_timing"), _event("tool_receipt", tool="query_drc")])
    assert decision.action == "stop" and decision.hypothesis["reason"] == "drc_violation"
