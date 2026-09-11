"""The sole Tutorial L1 typed-tool dispatcher.

This is intentionally distinct from the historical ``semantic_tools`` module:
it has no experiment object, optimizer policy, or local EDA handler.
"""
from __future__ import annotations

from typing import Any

from openroad_platform_contracts.agent_control import DesignGoal, DesignState, SemanticToolCall, ToolReceipt, ToolName
from openroad_platform_contracts.l1_tool_contract import (
    SemanticToolDefinition, SemanticToolRegistryContract, TUTORIAL_L1_TOOLS,
)

from .l1_semantic_policy import L1SemanticToolPolicy


_SIDE_EFFECTS = frozenset({ToolName.SET_FLOW_PARAMS, ToolName.RUN_STAGE,
                           ToolName.RUN_FULL_FLOW, ToolName.STOP_OR_ESCALATE})


def tutorial_l1_registry_contract() -> SemanticToolRegistryContract:
    """Capability discovery only; argument authority is L1SemanticToolPolicy."""
    definitions = tuple(SemanticToolDefinition(
        name=tool, version="v1", description=f"Typed L1 {tool.value} operation.",
        capability=("knowledge.openroad.retrieve"
                    if tool is ToolName.QUERY_OPENROAD_KNOWLEDGE else "eda.l1"),
        input_schema=({
            "type": "object", "additionalProperties": False,
            "required": ["query"],
            "properties": {"query": {"type": "string", "maxLength": 16384},
                           "purpose": {"enum": ["knowledge", "error_explanation"]},
                           "top_k": {"type": "integer", "minimum": 1, "maximum": 10}},
        } if tool is ToolName.QUERY_OPENROAD_KNOWLEDGE else {"type": "object"}),
        output_schema={"type": "object"},
        preconditions=("typed_goal", "current_state", "policy_allowlist"),
        postconditions=("durable_receipt",), side_effect=tool in _SIDE_EFFECTS,
        evidence_kinds=(("knowledge_retrieval", "knowledge_explanation")
                        if tool is ToolName.QUERY_OPENROAD_KNOWLEDGE
                        else ("runtime_evidence",)),
        permissions=("l1_policy",),
    ) for tool in sorted(TUTORIAL_L1_TOOLS, key=lambda item: item.value))
    contract = SemanticToolRegistryContract("l1-tutorial-v1", definitions)
    contract.validate()
    return contract


class L1RuntimeToolRegistry:
    """Validate once, then delegate the fixed surface to a Runtime bridge."""
    def __init__(self, bridge: Any) -> None:
        if frozenset(bridge.supported_tools()) != TUTORIAL_L1_TOOLS:
            raise ValueError("Runtime bridge does not implement the complete tutorial L1 tool surface")
        self._bridge = bridge
        self.contract = tutorial_l1_registry_contract()

    @staticmethod
    def validate(goal: DesignGoal, state: DesignState, call: SemanticToolCall) -> None:
        L1SemanticToolPolicy.validate(goal, state, call)

    def execute(self, goal: DesignGoal, state: DesignState, call: SemanticToolCall) -> ToolReceipt:
        self.validate(goal, state, call)
        receipt = self._bridge.execute(goal, state, call)
        receipt.validate()
        if (receipt.call_id, receipt.goal_id, receipt.state_id, receipt.tool) != (
                call.call_id, goal.goal_id, state.state_id, call.tool):
            raise ValueError("Runtime bridge receipt does not match the typed call")
        return receipt
