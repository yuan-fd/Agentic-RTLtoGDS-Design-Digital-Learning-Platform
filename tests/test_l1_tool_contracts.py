from __future__ import annotations

import pytest

from openroad_platform_contracts.agent_control import ToolName
from openroad_platform_contracts.l1_tool_contract import SemanticToolDefinition, SemanticToolRegistryContract, TUTORIAL_L1_TOOLS


def _definition(name: ToolName) -> SemanticToolDefinition:
    return SemanticToolDefinition(
        name=name, version="v1", description=f"Typed {name.value} operation",
        capability=f"eda.{name.value}", input_schema={"run_id": "RunId"},
        output_schema={"evidence_ref": "EvidenceRef"}, preconditions=("goal_authorized",),
        postconditions=("receipt_recorded",), side_effect=name in {
            ToolName.SET_FLOW_PARAMS, ToolName.RUN_STAGE, ToolName.RUN_FULL_FLOW,
            ToolName.STOP_OR_ESCALATE,
        }, evidence_kinds=("report",), permissions=("project_read",),
    )


def test_registry_requires_all_and_only_tutorial_tools() -> None:
    registry = SemanticToolRegistryContract("l1-openroad-v1", tuple(_definition(item) for item in TUTORIAL_L1_TOOLS))
    assert SemanticToolRegistryContract.from_dict(registry.to_dict()) == registry
    with pytest.raises(ValueError, match="exactly the tutorial"):
        SemanticToolRegistryContract("l1-openroad-v1", registry.definitions[:-1]).validate()
    with pytest.raises(ValueError, match="exactly the tutorial"):
        SemanticToolRegistryContract("l1-openroad-v1", registry.definitions + (registry.definitions[0],)).validate()


def test_definition_rejects_shell_surface() -> None:
    definition = _definition(ToolName.RUN_STAGE)
    forbidden = (
        "shell", "shell_command", "shellCommand", "cmd", "exec", "program", "argv",
        "credentialToken", "privateKey", "secret", "authorization", "accessKey",
    )
    for key in forbidden:
        with pytest.raises(ValueError, match="forbidden executable"):
            SemanticToolDefinition(**{**definition.__dict__, "input_schema": {"nested": [[{key: "string"}]]}}).validate()
