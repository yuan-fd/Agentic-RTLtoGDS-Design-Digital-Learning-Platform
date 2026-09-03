"""Compile an admitted SpecIR conversation result into L1 ``DesignGoal`` data."""

from __future__ import annotations

import hashlib
import json
from typing import Iterable

from openroad_platform_contracts import (
    AgentBudget, DesignGoal, EvidencePointer, GoalPreference, QoRConstraint,
)

from .spec_conversation import SpecProposal


_STAGE_ORDER = ("synth", "floorplan", "place", "cts", "route", "finish")


def infer_goal_preference(text: str) -> GoalPreference:
    """A transparent preference projection; it never changes hard constraints."""
    lowered = str(text).lower()
    if any(item in lowered for item in ("功耗", "power", "低功耗")):
        return GoalPreference.POWER
    if any(item in lowered for item in ("面积", "area", "smallest")):
        return GoalPreference.AREA
    if any(item in lowered for item in ("性能", "时序", "timing", "frequency", "fmax")):
        return GoalPreference.PERFORMANCE
    return GoalPreference.BALANCED


def compile_design_goal(*, goal_id: str, project_id: str, design_id: str,
                        proposal: SpecProposal, rtl_artifact: EvidencePointer,
                        pdk_id: str, toolchain_id: str,
                        allowed_parameters: Iterable[str],
                        budget: AgentBudget) -> DesignGoal:
    """Create the sole executable L1 entry after RTL verification is complete."""
    if not proposal.ready_for_execution:
        raise ValueError("cannot compile DesignGoal from an incomplete SpecIR proposal")
    rtl_artifact.validate(); budget.validate()
    try:
        target_index = _STAGE_ORDER.index(proposal.target_stage)
    except ValueError as exc:
        raise ValueError("SpecIR target stage is unsupported") from exc
    parameters = tuple(str(item) for item in allowed_parameters)
    goal = DesignGoal(
        goal_id=goal_id, project_id=project_id, design_id=design_id,
        platform=proposal.target_platform, pdk_id=pdk_id,
        toolchain_id=toolchain_id, rtl_artifact=rtl_artifact,
        preference=infer_goal_preference(proposal.objective),
        hard_constraints=(
            QoRConstraint("setup_wns_ns", ">=", 0.0),
            QoRConstraint("drc_errors", "<=", 0.0),
        ),
        allowed_stages=_STAGE_ORDER[:target_index + 1],
        allowed_parameters=parameters, budget=budget,
        labels={
            "specir_target_stage": proposal.target_stage,
            "specir_fingerprint": hashlib.sha256(json.dumps(
                proposal.to_dict(), sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        },
    )
    goal.validate()
    return goal
