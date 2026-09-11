from __future__ import annotations

import pytest

from apps.l1_workbench.tutorial_profile import ManagedTutorialProfile
from openroad_platform_contracts.agent_control import AgentBudget, GoalPreference, QoRConstraint, ToolName
from openroad_platform_contracts.l1_goal_draft import ClarificationAnswer, GoalDraft, GoalIntent
from openroad_platform_contracts.learning import EvidencePointer
from openroad_platform_scheduler.l1_goal_finalizer import TrustedGoalPolicy


def _policy() -> TrustedGoalPolicy:
    return TrustedGoalPolicy(
        "policy_1", "v1", "platform", EvidencePointer("artifact:policy", "b" * 64),
        "tutorial_mux", "mux_2to1", "nangate45", "nangate45", "orfs_2d", 
        EvidencePointer("artifact:rtl", "a" * 64), GoalPreference.BALANCED,
        (QoRConstraint("l1_tool_runs", ">=", 1),), ("finish",),
        ("core_utilization_pct", "place_density"), AgentBudget(3, 4, 7200),
        (ToolName.RUN_FULL_FLOW, ToolName.STOP_OR_ESCALATE),
    )


def _draft(profile: ManagedTutorialProfile, answers: dict[str, str]) -> GoalDraft:
    values = {**answers, "design_context": answers.get(
        "design_context", profile.design_context,
    )}
    return GoalDraft(
        "draft_1", "Improve timing but protect RTL and SDC.", GoalIntent.OPTIMIZE,
        questions=profile.questions(),
        answers=tuple(ClarificationAnswer(question_id, question.field, values[question_id])
                      for question_id, question in ((item.question_id, item) for item in profile.questions())),
        parser_id="test_provider",
    )


def test_profile_compiles_only_approved_answers_into_a_real_goal() -> None:
    profile = ManagedTutorialProfile()
    goal = profile.compile(_draft(profile, {
        "objective": "timing", "constraints": "drc_zero_area_plus_3pct",
        "clock_sdc": "protect_clock_sdc", "change_scope": "registered_parameters_only",
        "budget": "3",
    }), _policy(), goal_id="goal_1")
    assert goal.preference is GoalPreference.PERFORMANCE
    assert goal.budget.max_eda_runs == 3
    assert {(item.metric, item.operator, item.threshold) for item in goal.hard_constraints} == {
        ("setup_wns_ns", ">=", 0.0), ("drc_errors", "<=", 0.0),
        ("area_baseline_ratio", "<=", 1.03),
    }
    assert goal.labels["l1_profile_id"] == "orfs_mux_baseline_v1"
    assert goal.labels["l1_clock_sdc"] == "protect_clock_sdc"


def test_profile_records_operator_owned_aes_reference_identity() -> None:
    profile = ManagedTutorialProfile(
        profile_id="orfs_agent_paper_aes_sky130hd_l1_v1",
        design_context="managed_aes_sky130hd_4p5ns_paper_baseline",
        design_label="managed_aes_sky130hd_reference",
    )
    goal = profile.compile(_draft(profile, {
        "objective": "timing", "constraints": "drc_zero_area_plus_3pct",
        "clock_sdc": "protect_clock_sdc",
        "change_scope": "registered_parameters_only", "budget": "3",
    }), _policy(), goal_id="goal_aes")
    assert goal.labels["l1_profile_id"] == "orfs_agent_paper_aes_sky130hd_l1_v1"
    assert goal.labels["l1_profile_design_context"] == \
        "managed_aes_sky130hd_reference"


@pytest.mark.parametrize("field,value", [
    ("objective", "make_it_best"), ("budget", "50"),
    ("constraints", "remove_drc_limit"), ("clock_sdc", "allow_clock_change"),
    ("change_scope", "edit_rtl"),
])
def test_profile_rejects_unapproved_user_intent(field: str, value: str) -> None:
    profile = ManagedTutorialProfile()
    answers = {
        "objective": "timing", "constraints": "drc_zero_area_plus_3pct",
        "clock_sdc": "protect_clock_sdc", "change_scope": "registered_parameters_only",
        "budget": "2",
    }
    answers[field] = value
    with pytest.raises(ValueError):
        profile.compile(_draft(profile, answers), _policy(), goal_id="goal_1")
