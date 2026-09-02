from __future__ import annotations

import pytest

from openroad_platform_contracts.agent_control import AgentBudget, GoalPreference, QoRConstraint, ToolName
from openroad_platform_contracts.l1_goal_draft import (
    ClarificationAnswer, ClarificationField, ClarificationQuestion, GoalDraft, GoalIntent,
)
from openroad_platform_contracts.learning import EvidencePointer
from openroad_platform_scheduler.l1_goal_finalizer import GoalFinalizer, TrustedGoalPolicy


def _policy() -> TrustedGoalPolicy:
    return TrustedGoalPolicy(
        policy_id="l1-policy-1", policy_version="v1", issuer="platform-policy-service",
        provenance=EvidencePointer("artifact:policy", "d" * 64),
        project_id="project-1", design_id="aes", platform="sky130hd", pdk_id="sky130hd",
        toolchain_id="pinned-toolchain", rtl_artifact=EvidencePointer("artifact:rtl", "a" * 64),
        preference=GoalPreference.PERFORMANCE,
        hard_constraints=(QoRConstraint("setup_wns_ns", ">=", 0.0),),
        allowed_stages=("synth", "place", "route", "finish"),
        allowed_parameters=("core_utilization_pct",), budget=AgentBudget(3, 3, 3600, 1),
        allowed_tools=(ToolName.QUERY_TIMING, ToolName.RUN_STAGE, ToolName.STOP_OR_ESCALATE),
    )


def _draft(answered: bool) -> GoalDraft:
    question = ClarificationQuestion("clock-policy", ClarificationField.CLOCK_SDC_POLICY,
                                     "May clock or SDC be changed?")
    answers = (ClarificationAnswer("clock-policy", ClarificationField.CLOCK_SDC_POLICY,
                                   "No; both are protected"),) if answered else ()
    return GoalDraft("draft-1", "Improve timing without changing clock", GoalIntent.OPTIMIZE,
                     questions=(question,), answers=answers, parser_id="structured-provider")


def test_finalizer_requires_answered_draft_and_records_only_policy_facts() -> None:
    with pytest.raises(ValueError, match="unresolved"):
        GoalFinalizer.finalize(_draft(False), _policy(), goal_id="goal-1")
    goal = GoalFinalizer.finalize(_draft(True), _policy(), goal_id="goal-1")
    assert goal.design_id == "aes"
    assert goal.labels["l1_draft_sha256"] == _draft(True).request_sha256
    assert goal.labels["l1_policy_provenance"] == "artifact:policy"
    assert goal.allowed_parameters == ("core_utilization_pct",)
