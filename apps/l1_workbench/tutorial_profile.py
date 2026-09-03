"""Operator-owned L1 tutorial profile and deterministic Goal compiler.

This module deliberately recognizes a small closed vocabulary.  It is not an
LLM, natural-language shell translator, or optimizer.  A future structured
provider may propose the same typed answers, but the profile remains the sole
authority that maps them to an executable DesignGoal.
"""
from __future__ import annotations

from dataclasses import replace

from openroad_platform_contracts.agent_control import AgentBudget, GoalPreference, QoRConstraint
from openroad_platform_contracts.l1_goal_draft import ClarificationField, ClarificationQuestion, GoalDraft
from openroad_platform_scheduler.l1_goal_finalizer import GoalFinalizer, TrustedGoalPolicy


class ManagedTutorialProfile:
    """One bounded mux/ORFS exercise; profile values are never user-writable."""

    profile_id = "orfs_mux_baseline_v1"
    _objectives = {
        "timing": GoalPreference.PERFORMANCE,
        "balanced": GoalPreference.BALANCED,
        "area": GoalPreference.AREA,
        "power": GoalPreference.POWER,
    }
    _budgets = {"1": 1, "2": 2, "3": 3}
    _required = (
        ("objective", ClarificationField.OBJECTIVE,
         "Choose objective: timing, balanced, area, or power."),
        ("constraints", ClarificationField.CONSTRAINTS,
         "Confirm constraints exactly: drc_zero_area_plus_3pct."),
        ("clock_sdc", ClarificationField.CLOCK_SDC_POLICY,
         "Confirm protected inputs exactly: protect_clock_sdc."),
        ("change_scope", ClarificationField.CHANGE_SCOPE,
         "Confirm change scope exactly: registered_parameters_only."),
        ("budget", ClarificationField.BUDGET,
         "Choose maximum EDA runs: 1, 2, or 3."),
    )

    def questions(self) -> tuple[ClarificationQuestion, ...]:
        return tuple(ClarificationQuestion(question_id, field, prompt, True)
                     for question_id, field, prompt in self._required)

    def compile(self, draft: GoalDraft, policy: TrustedGoalPolicy, *, goal_id: str):
        draft.validate(); policy.validate()
        if draft.unresolved_blocking_fields():
            raise ValueError("tutorial Goal compilation requires all blocking clarifications")
        answers = {item.question_id: item.value.strip().lower() for item in draft.answers}
        if set(answers) != {item[0] for item in self._required}:
            raise ValueError("tutorial Goal has missing or unexpected clarification answers")
        try:
            preference = self._objectives[answers["objective"]]
            runs = self._budgets[answers["budget"]]
        except KeyError as exc:
            raise ValueError("tutorial objective or budget is outside the approved vocabulary") from exc
        if answers["constraints"] != "drc_zero_area_plus_3pct":
            raise ValueError("tutorial constraints must preserve DRC=0 and area baseline cap")
        if answers["clock_sdc"] != "protect_clock_sdc":
            raise ValueError("clock and SDC are protected in this tutorial profile")
        if answers["change_scope"] != "registered_parameters_only":
            raise ValueError("tutorial profile only permits registered parameter changes")
        if runs > policy.budget.max_eda_runs:
            raise ValueError("tutorial requested run budget exceeds operator policy")
        compiled = replace(
            policy,
            preference=preference,
            hard_constraints=(
                QoRConstraint("setup_wns_ns", ">=", 0.0),
                QoRConstraint("drc_errors", "<=", 0.0),
                QoRConstraint("area_baseline_ratio", "<=", 1.03),
            ),
            budget=AgentBudget(runs, policy.budget.max_llm_calls,
                               policy.budget.max_wall_clock_seconds,
                               policy.budget.max_parallel),
        )
        goal = GoalFinalizer.finalize(draft, compiled, goal_id=goal_id)
        return replace(goal, labels={
            **goal.labels,
            "l1_profile_id": self.profile_id,
            "l1_profile_design_context": "managed_tutorial_mux",
            "l1_profile_toolchain": policy.toolchain_id,
            "l1_objective": answers["objective"],
            "l1_constraints": answers["constraints"],
            "l1_clock_sdc": answers["clock_sdc"],
            "l1_change_scope": answers["change_scope"],
            "l1_requested_eda_runs": str(runs),
        })
