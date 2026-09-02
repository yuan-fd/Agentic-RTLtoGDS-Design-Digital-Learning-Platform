"""Versioned, backend-neutral L1 semantic EDA tool contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from .agent_control import ToolName
from .platform import SCHEMA_VERSION, _known_payload, _primitive, _validate_identifier, _validate_mapping, _validate_version


TUTORIAL_L1_TOOLS = frozenset({
    ToolName.GET_DESIGN_SUMMARY, ToolName.QUERY_TIMING, ToolName.QUERY_CONGESTION,
    ToolName.QUERY_DRC, ToolName.QUERY_POWER, ToolName.QUERY_STAGE_METRICS,
    ToolName.QUERY_ARTIFACT_EXCERPT, ToolName.SET_FLOW_PARAMS, ToolName.RUN_STAGE,
    ToolName.RUN_FULL_FLOW, ToolName.COMPARE_RUNS, ToolName.STOP_OR_ESCALATE,
})


_FORBIDDEN_SCHEMA_TERMS = frozenset({
    "command", "cmd", "shell", "tcl", "script", "executable", "exec", "program", "argv",
    "path", "cwd", "env", "environment", "credential", "api_key", "access_key",
    "private_key", "secret", "authorization", "token", "password",
    "chain_of_thought", "hidden_reasoning",
})


def reject_forbidden_field_tree(name: str, value: Mapping[str, Any]) -> None:
    """Reject unsafe keys in a JSON-like mapping despite spelling variants."""
    _validate_mapping(name, value)
    _reject_forbidden_value(name, value)


def _reject_forbidden_value(name: str, value: Any) -> None:
    forbidden_compact = {term.replace("_", "") for term in _FORBIDDEN_SCHEMA_TERMS}
    if isinstance(value, (tuple, list)):
        for item in value:
            _reject_forbidden_value(name, item)
        return
    if not isinstance(value, Mapping):
        return
    for key, item in value.items():
        if not isinstance(key, str):
            raise ValueError(f"{name} keys must be strings")
        snake_case = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key).lower()
        tokens = tuple(part for part in re.split(r"[^a-z0-9]+", snake_case) if part)
        compact = "".join(tokens)
        if snake_case in _FORBIDDEN_SCHEMA_TERMS or compact in forbidden_compact or any(token in _FORBIDDEN_SCHEMA_TERMS for token in tokens):
            raise ValueError(f"{name} contains forbidden executable field {key!r}")
        _reject_forbidden_value(name, item)


def _identifier_list(name: str, values: tuple[str, ...]) -> None:
    if not isinstance(values, tuple) or not values:
        raise ValueError(f"{name} must be a non-empty tuple")
    if len(set(values)) != len(values):
        raise ValueError(f"{name} must be unique")
    for value in values:
        _validate_identifier(name, value)


def _schema(name: str, value: Mapping[str, Any]) -> None:
    reject_forbidden_field_tree(name, value)
    for item in value.values():
        _schema_value(name, item)


def _schema_value(name: str, value: Any) -> None:
    if isinstance(value, Mapping):
        _schema(name, value)
    elif isinstance(value, (tuple, list)):
        for child in value:
            _schema_value(name, child)


@dataclass(frozen=True)
class SemanticToolDefinition:
    name: ToolName
    version: str
    description: str
    capability: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    preconditions: tuple[str, ...]
    postconditions: tuple[str, ...]
    side_effect: bool
    evidence_kinds: tuple[str, ...]
    permissions: tuple[str, ...]
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        if not isinstance(self.name, ToolName):
            raise ValueError("semantic tool name must be typed")
        _validate_identifier("tool version", self.version)
        _validate_identifier("tool capability", self.capability)
        if not isinstance(self.description, str) or not self.description.strip() or len(self.description) > 2000:
            raise ValueError("tool description must be bounded non-empty text")
        _schema("input_schema", self.input_schema)
        _schema("output_schema", self.output_schema)
        _identifier_list("preconditions", self.preconditions)
        _identifier_list("postconditions", self.postconditions)
        _identifier_list("evidence_kinds", self.evidence_kinds)
        _identifier_list("permissions", self.permissions)
        if not isinstance(self.side_effect, bool):
            raise ValueError("side_effect must be boolean")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SemanticToolDefinition":
        value = _known_payload(cls, payload)
        value["name"] = ToolName(value["name"])
        for field in ("preconditions", "postconditions", "evidence_kinds", "permissions"):
            value[field] = tuple(value.get(field, ()))
        result = cls(**value)
        result.validate()
        return result


@dataclass(frozen=True)
class SemanticToolRegistryContract:
    registry_id: str
    definitions: tuple[SemanticToolDefinition, ...]
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        _validate_identifier("registry_id", self.registry_id)
        if not isinstance(self.definitions, tuple) or not self.definitions:
            raise ValueError("registry definitions must be a non-empty tuple")
        for definition in self.definitions:
            if not isinstance(definition, SemanticToolDefinition):
                raise ValueError("registry definitions must contain SemanticToolDefinition values")
            definition.validate()
        if len(self.definitions) != len(TUTORIAL_L1_TOOLS) or {item.name for item in self.definitions} != TUTORIAL_L1_TOOLS:
            raise ValueError("registry must define exactly the tutorial L1 tool surface")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SemanticToolRegistryContract":
        value = _known_payload(cls, payload)
        value["definitions"] = tuple(SemanticToolDefinition.from_dict(item)
                                     for item in value.get("definitions", ()))
        result = cls(**value)
        result.validate()
        return result
