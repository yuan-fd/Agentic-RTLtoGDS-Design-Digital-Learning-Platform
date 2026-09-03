"""L1 semantic-tool gate for OpenROAD physical-design agents.

This module deliberately has no shell/process API.  Tool handlers are supplied
by the Runtime integration and may only be reached after a typed call has been
checked against the immutable :class:`DesignGoal` and its current
:class:`DesignState`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from openroad_platform_contracts import (
    DesignGoal,
    DesignState,
    READ_ONLY_TOOLS,
    SemanticToolCall,
    ToolName,
    ToolReceipt,
)


ToolHandler = Callable[[DesignGoal, DesignState, SemanticToolCall], ToolReceipt]


@dataclass(frozen=True)
class ToolDefinition:
    tool: ToolName
    mutates_state: bool
    handler: ToolHandler


class SemanticToolPolicy:
    """Validate calls before they can reach an execution adapter.

    The policy owns argument schemas because an LLM must not expand a tool's
    surface area merely by inventing a JSON field.  Runtime-specific checks
    (such as a registered artifact/run id) are then made by the handler.
    """

    @staticmethod
    def validate(goal: DesignGoal, state: DesignState, call: SemanticToolCall) -> None:
        goal.validate(); state.validate(); call.validate()
        if call.goal_id != goal.goal_id or call.state_id != state.state_id:
            raise ValueError("SemanticToolCall does not bind to the supplied goal/state")
        if state.goal_id != goal.goal_id:
            raise ValueError("DesignState belongs to a different goal")
        if call.tool not in goal.allowed_tools:
            raise ValueError("SemanticToolCall tool is not allowlisted by DesignGoal")
        if state.status in {"stopped", "completed"} and call.tool not in READ_ONLY_TOOLS:
            raise ValueError("A terminal DesignState permits read-only tools only")
        if call.tool is ToolName.CREATE_EXPERIMENT:
            _exact(call.arguments, {"name", "or_seed"}, required={"name"})
            _text(call.arguments["name"], "name", maximum=128)
            _optional_seed(call.arguments.get("or_seed"))
        elif call.tool is ToolName.SET_FLOW_PARAMS:
            _exact(call.arguments, {"experiment_id", "values"},
                   required={"experiment_id", "values"})
            _identifier_text(call.arguments["experiment_id"], "experiment_id")
            values = call.arguments["values"]
            if not isinstance(values, Mapping) or not values:
                raise ValueError("set_flow_params requires a non-empty values object")
            unknown = sorted(set(values) - set(goal.allowed_parameters))
            if unknown:
                raise ValueError("set_flow_params contains unallowlisted parameter: " + ", ".join(unknown))
            # The contracts already reject non-JSON values.  This branch adds a
            # precise semantic error for nested parameter payloads.
            if any(isinstance(value, (Mapping, list, tuple))
                   or value is None for value in values.values()):
                raise ValueError("set_flow_params values must be scalar")
        elif call.tool is ToolName.RUN_STAGE:
            _exact(call.arguments, {"stage", "experiment_id"}, required={"stage", "experiment_id"})
            stage = call.arguments["stage"]
            if stage not in goal.allowed_stages:
                raise ValueError("run_stage is outside the DesignGoal stage policy")
            _identifier_text(call.arguments["experiment_id"], "experiment_id")
        elif call.tool in {
            ToolName.QUERY_TIMING, ToolName.QUERY_CONGESTION, ToolName.QUERY_DRC,
            ToolName.QUERY_POWER,
        }:
            _exact(call.arguments, {"run_id", "limit"}, required={"run_id"})
            _identifier_text(call.arguments["run_id"], "run_id")
            _bounded_limit(call.arguments.get("limit"))
        elif call.tool is ToolName.QUERY_ARTIFACT_EXCERPT:
            _exact(call.arguments, {"artifact_id", "offset", "max_bytes"},
                   required={"artifact_id", "max_bytes"})
            _identifier_text(call.arguments["artifact_id"], "artifact_id")
            _nonnegative_int(call.arguments.get("offset", 0), "offset", maximum=64 * 1024 * 1024)
            _nonnegative_int(call.arguments["max_bytes"], "max_bytes", maximum=64 * 1024)
            if call.arguments["max_bytes"] == 0:
                raise ValueError("max_bytes must be positive")
        elif call.tool is ToolName.COMPARE_RUNS:
            _exact(call.arguments, {"left_run_id", "right_run_id", "metrics"},
                   required={"left_run_id", "right_run_id"})
            _identifier_text(call.arguments["left_run_id"], "left_run_id")
            _identifier_text(call.arguments["right_run_id"], "right_run_id")
            if call.arguments["left_run_id"] == call.arguments["right_run_id"]:
                raise ValueError("compare_runs requires two distinct runs")
            _metric_list(call.arguments.get("metrics", ()))
        elif call.tool is ToolName.STOP_OR_ESCALATE:
            _exact(call.arguments, {"reason", "target_level"}, required={"reason"})
            _text(call.arguments["reason"], "reason", maximum=1000)
            if call.arguments.get("target_level") not in {None, "human", "L3", "L4"}:
                raise ValueError("stop_or_escalate target_level is unsupported")
        else:  # Defensive guard for future enum additions.
            raise ValueError("SemanticToolCall tool has no scheduler policy")


class SemanticToolRegistry:
    """Registry and protected dispatcher for L1 semantic tools."""

    def __init__(self) -> None:
        self._definitions: dict[ToolName, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        if definition.tool in self._definitions:
            raise ValueError(f"semantic tool already registered: {definition.tool.value}")
        self._definitions[definition.tool] = definition

    def execute(self, goal: DesignGoal, state: DesignState,
                call: SemanticToolCall) -> ToolReceipt:
        SemanticToolPolicy.validate(goal, state, call)
        try:
            definition = self._definitions[call.tool]
        except KeyError as exc:
            raise ValueError(f"semantic tool is not installed: {call.tool.value}") from exc
        receipt = definition.handler(goal, state, call)
        receipt.validate()
        if (receipt.call_id, receipt.goal_id, receipt.state_id, receipt.tool) != (
            call.call_id, goal.goal_id, state.state_id, call.tool,
        ):
            raise ValueError("ToolReceipt identity does not match the dispatched call")
        if definition.mutates_state and receipt.status in {"accepted", "completed"} and not receipt.next_state_id:
            raise ValueError("an accepted or completed mutating tool must produce a successor state")
        if not definition.mutates_state and receipt.next_state_id is not None:
            raise ValueError("a read-only tool may not produce a successor state")
        return receipt

    def installed_tools(self) -> tuple[ToolName, ...]:
        return tuple(sorted(self._definitions, key=lambda item: item.value))


def _exact(arguments: Mapping[str, Any], allowed: set[str], *, required: set[str]) -> None:
    unknown = sorted(set(arguments) - allowed)
    if unknown:
        raise ValueError("semantic tool arguments contain unknown fields: " + ", ".join(unknown))
    missing = sorted(required - set(arguments))
    if missing:
        raise ValueError("semantic tool arguments are missing fields: " + ", ".join(missing))


def _text(value: Any, name: str, *, maximum: int) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{name} must be non-empty text up to {maximum} characters")


def _identifier_text(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ValueError(f"{name} must be a bounded identifier")


def _optional_seed(value: Any) -> None:
    if value is not None:
        _nonnegative_int(value, "or_seed", maximum=2_147_483_647)


def _bounded_limit(value: Any) -> None:
    if value is not None:
        _nonnegative_int(value, "limit", maximum=256)
        if value == 0:
            raise ValueError("limit must be positive")


def _nonnegative_int(value: Any, name: str, *, maximum: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= maximum:
        raise ValueError(f"{name} is outside policy")


def _metric_list(value: Any) -> None:
    if not isinstance(value, (tuple, list)) or len(value) > 16:
        raise ValueError("metrics must be a list containing at most 16 names")
    for item in value:
        _identifier_text(item, "metric")