from __future__ import annotations

import pytest

from openroad_platform_contracts.l1_tool_contract import (
    L1ToolName,
    SemanticToolDefinition,
    SemanticToolRegistryContract,
)


def _definition(name: L1ToolName) -> SemanticToolDefinition:
    return SemanticToolDefinition(
        name=name, version="v1", description=f"Typed {name.value} operation",
        capability=f"eda.{name.value}", input_schema={"run_id": "RunId"},
        output_schema={"evidence_ref": "EvidenceRef"}, preconditions=("goal_authorized",),
        postconditions=("receipt_recorded",), side_effect=name in {
            L1ToolName.SET_FLOW_PARAMS, L1ToolName.RUN_STAGE, L1ToolName.RUN_FULL_FLOW,
            L1ToolName.STOP_OR_ESCALATE,
        }, evidence_kinds=("report",), permissions=("project_read",),
    )


def test_registry_requires_all_and_only_tutorial_tools() -> None:
    registry = SemanticToolRegistryContract("l1-openroad-v1", tuple(_definition(item) for item in L1ToolName))
    assert SemanticToolRegistryContract.from_dict(registry.to_dict()) == registry
    with pytest.raises(ValueError, match="exactly the tutorial"):
        SemanticToolRegistryContract("l1-openroad-v1", registry.definitions[:-1]).validate()


def test_definition_rejects_shell_surface() -> None:
    definition = _definition(L1ToolName.RUN_STAGE)
    with pytest.raises(ValueError, match="forbidden executable"):
        SemanticToolDefinition(**{**definition.__dict__, "input_schema": {"shell": "string"}}).validate()
