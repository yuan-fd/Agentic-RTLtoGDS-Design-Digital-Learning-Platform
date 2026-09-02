"""The single scheduler policy for the tutorial's fixed L1 tool protocol."""
from __future__ import annotations

from typing import Any, Mapping

from openroad_platform_contracts.agent_control import DesignGoal, DesignState, SemanticToolCall, ToolName
from openroad_platform_contracts.l1_tool_contract import TUTORIAL_L1_TOOLS


class L1SemanticToolPolicy:
    """Validate every L1 call before a bridge may read or mutate Runtime."""
    @classmethod
    def validate(cls, goal: DesignGoal, state: DesignState, call: SemanticToolCall) -> None:
        goal.validate(); state.validate(); call.validate()
        if state.goal_id != goal.goal_id or call.goal_id != goal.goal_id or call.state_id != state.state_id:
            raise ValueError("semantic call does not bind the supplied goal/state")
        if call.tool not in TUTORIAL_L1_TOOLS or call.tool not in goal.allowed_tools:
            raise ValueError("semantic tool is not allowed by the finalized DesignGoal")
        a = call.arguments
        if call.tool is ToolName.GET_DESIGN_SUMMARY:
            cls._exact(a, set())
        elif call.tool in {ToolName.QUERY_TIMING, ToolName.QUERY_CONGESTION, ToolName.QUERY_DRC,
                           ToolName.QUERY_POWER, ToolName.QUERY_STAGE_METRICS}:
            cls._exact(a, {"run_id", "limit"}, {"run_id"}); cls._id(a["run_id"], "run_id"); cls._limit(a.get("limit"))
        elif call.tool is ToolName.QUERY_ARTIFACT_EXCERPT:
            cls._exact(a, {"run_id", "artifact_id", "offset", "max_bytes"}, {"run_id", "artifact_id", "max_bytes"})
            cls._id(a["run_id"], "run_id"); cls._id(a["artifact_id"], "artifact_id"); cls._integer(a.get("offset", 0), "offset", 64 * 1024 * 1024); cls._integer(a["max_bytes"], "max_bytes", 64 * 1024)
            if not a["max_bytes"]: raise ValueError("max_bytes must be positive")
        elif call.tool is ToolName.SET_FLOW_PARAMS:
            cls._exact(a, {"values"}, {"values"}); values = a["values"]
            if not isinstance(values, Mapping) or not values or set(values) - set(goal.allowed_parameters): raise ValueError("parameter values are outside DesignGoal policy")
        elif call.tool is ToolName.RUN_STAGE:
            cls._exact(a, {"stage", "parameter_patch", "proposal_id"}, {"stage"})
            if a["stage"] not in goal.allowed_stages: raise ValueError("stage is outside DesignGoal policy")
            cls._patch(a.get("parameter_patch"), goal)
        elif call.tool is ToolName.RUN_FULL_FLOW:
            cls._exact(a, {"parameter_patch", "proposal_id"}); cls._patch(a.get("parameter_patch"), goal)
        elif call.tool is ToolName.COMPARE_RUNS:
            cls._exact(a, {"left_run_id", "right_run_id", "metrics"}, {"left_run_id", "right_run_id", "metrics"})
            cls._id(a["left_run_id"], "left_run_id"); cls._id(a["right_run_id"], "right_run_id")
            if a["left_run_id"] == a["right_run_id"] or not isinstance(a["metrics"], list) or not a["metrics"]: raise ValueError("compare_runs requires distinct runs and metrics")
        elif call.tool is ToolName.STOP_OR_ESCALATE:
            cls._exact(a, {"run_id", "reason", "target_level"}, {"run_id", "reason"}); cls._id(a["run_id"], "run_id")
            if not isinstance(a["reason"], str) or not a["reason"].strip() or len(a["reason"]) > 1000: raise ValueError("stop reason is invalid")
            if a.get("target_level") not in {None, "human", "L3", "L4"}: raise ValueError("target_level is invalid")

    @staticmethod
    def _exact(value: Mapping[str, Any], allowed: set[str], required: set[str] = set()) -> None:
        if set(value) - allowed or required - set(value): raise ValueError("semantic tool arguments do not match the fixed contract")
    @staticmethod
    def _id(value: Any, name: str) -> None:
        if not isinstance(value, str) or not value or len(value) > 128: raise ValueError(f"{name} is invalid")
    @staticmethod
    def _integer(value: Any, name: str, maximum: int) -> None:
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= maximum: raise ValueError(f"{name} is invalid")
    @classmethod
    def _limit(cls, value: Any) -> None:
        if value is not None:
            cls._integer(value, "limit", 256)
            if not value: raise ValueError("limit must be positive")
    @staticmethod
    def _patch(value: Any, goal: DesignGoal) -> None:
        if value is not None and (not isinstance(value, Mapping) or set(value) - set(goal.allowed_parameters)):
            raise ValueError("parameter_patch is outside DesignGoal policy")
