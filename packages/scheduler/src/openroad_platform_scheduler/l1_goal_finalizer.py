"""Finalize an answered L1 language draft using trusted platform policy."""

from __future__ import annotations

from dataclasses import dataclass

from openroad_platform_contracts.agent_control import (
    AgentBudget, DesignGoal, GoalPreference, QoRConstraint, ToolName,
)
from openroad_platform_contracts.l1_goal_draft import GoalDraft
from openroad_platform_contracts.learning import EvidencePointer


@dataclass(frozen=True)
class TrustedGoalPolicy:
    """Operator-owned data needed to turn an untrusted draft into a goal."""

    policy_id: str
    policy_version: str
    issuer: str
    provenance: EvidencePointer
    project_id: str
    design_id: str
    platform: str
    pdk_id: str
    toolchain_id: str
    rtl_artifact: EvidencePointer
    preference: GoalPreference
    hard_constraints: tuple[QoRConstraint, ...]
    allowed_stages: tuple[str, ...]
    allowed_parameters: tuple[str, ...]
    budget: AgentBudget
    allowed_tools: tuple[ToolName, ...]

    def validate(self) -> None:
        if not all(isinstance(value, str) and value and len(value) <= 128
                   for value in (self.policy_id, self.policy_version, self.issuer)):
            raise ValueError("verified goal policy requires bounded id, version, and issuer")
        self.provenance.validate()
        # Reuse the public contract as the definitive policy validator.
        DesignGoal(
            goal_id="policy-validation", project_id=self.project_id, design_id=self.design_id,
            platform=self.platform, pdk_id=self.pdk_id, toolchain_id=self.toolchain_id,
            rtl_artifact=self.rtl_artifact, preference=self.preference,
            hard_constraints=self.hard_constraints, allowed_stages=self.allowed_stages,
            allowed_parameters=self.allowed_parameters, budget=self.budget,
            allowed_tools=self.allowed_tools,
        ).validate()


class GoalFinalizer:
    """A deterministic boundary; it neither calls an LLM nor executes tools."""

    @staticmethod
    def finalize(draft: GoalDraft, policy: TrustedGoalPolicy, *, goal_id: str) -> DesignGoal:
        draft.validate()
        policy.validate()
        missing = draft.unresolved_blocking_fields()
        if missing:
            raise ValueError("goal draft has unresolved blocking clarifications: " + ", ".join(item.value for item in missing))
        goal = DesignGoal(
            goal_id=goal_id, project_id=policy.project_id, design_id=policy.design_id,
            platform=policy.platform, pdk_id=policy.pdk_id, toolchain_id=policy.toolchain_id,
            rtl_artifact=policy.rtl_artifact, preference=policy.preference,
            hard_constraints=policy.hard_constraints, allowed_stages=policy.allowed_stages,
            allowed_parameters=policy.allowed_parameters, budget=policy.budget,
            allowed_tools=policy.allowed_tools,
            labels={"l1_draft_sha256": draft.request_sha256, "l1_parser_id": draft.parser_id,
                    "l1_policy_id": policy.policy_id, "l1_policy_version": policy.policy_version,
                    "l1_policy_issuer": policy.issuer, "l1_policy_provenance": policy.provenance.ref,
                    "l1_policy_provenance_sha256": policy.provenance.sha256},
        )
        goal.validate()
        return goal
