"""Versioned, backend-neutral L1 semantic EDA tool contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from .platform import SCHEMA_VERSION, _known_payload, _primitive, _validate_identifier, _validate_mapping, _validate_version


class L1ToolName(str, Enum):
    GET_DESIGN_SUMMARY = "get_design_summary"
    QUERY_TIMING = "query_timing"
    QUERY_CONGESTION = "query_congestion"
    QUERY_DRC = "query_drc"
    QUERY_POWER = "query_power"
    QUERY_STAGE_METRICS = "query_stage_metrics"
    GET_ARTIFACT_EXCERPT = "get_artifact_excerpt"
    SET_FLOW_PARAMS = "set_flow_params"
    RUN_STAGE = "run_stage"
    RUN_FULL_FLOW = "run_full_flow"
    COMPARE_RUNS = "compare_runs"
    STOP_OR_ESCALATE = "stop_or_escalate"


_FORBIDDEN_SCHEMA_TERMS = frozenset({
    "command", "shell", "script", "executable", "path", "cwd", "env",
    "environment", "credential", "api_key", "token", "password",
})


def _identifier_list(name: str, values: tuple[str, ...]) -> None:
    if not isinstance(values, tuple) or not values:
        raise ValueError(f"{name} must be a non-empty tuple")
    if len(set(values)) != len(values):
        raise ValueError(f"{name} must be unique")
    for value in values:
        _validate_identifier(name, value)


def _schema(name: str, value: Mapping[str, Any]) -> None:
    _validate_mapping(name, value)
    for key in value:
        if key.lower() in _FORBIDDEN_SCHEMA_TERMS:
            raise ValueError(f"{name} contains forbidden executable field {key!r}")


@dataclass(frozen=True)
class SemanticToolDefinition:
    name: L1ToolName
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
        if not isinstance(self.name, L1ToolName):
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
        value["name"] = L1ToolName(value["name"])
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
        if {item.name for item in self.definitions} != set(L1ToolName):
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
