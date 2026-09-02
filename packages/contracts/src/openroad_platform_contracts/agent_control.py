"""Typed contracts for the L1 tool-using physical-design agent.

These objects are intentionally data-only.  They are the boundary between an
LLM policy and the scheduler: an LLM may propose a :class:`SemanticToolCall`,
but only the scheduler may validate and execute it.  No contract contains a
shell command, executable path, credential, or mutable OpenROAD command.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from .learning import EvidencePointer
from .platform import (
    IDENTIFIER, SCHEMA_VERSION, _known_payload, _primitive,
    _validate_identifier, _validate_mapping, _validate_version,
)


class GoalPreference(str, Enum):
    BALANCED = "balanced"
    AREA = "area"
    POWER = "power"
    PERFORMANCE = "performance"


class ToolName(str, Enum):
    CREATE_EXPERIMENT = "create_experiment"
    SET_FLOW_PARAMS = "set_flow_params"
    RUN_STAGE = "run_stage"
    QUERY_TIMING = "query_timing"
    QUERY_CONGESTION = "query_congestion"
    QUERY_DRC = "query_drc"
    QUERY_POWER = "query_power"
    QUERY_ARTIFACT_EXCERPT = "query_artifact_excerpt"
    COMPARE_RUNS = "compare_runs"
    PROPOSE_SEARCH_POLICY = "propose_search_policy"
    STOP_OR_ESCALATE = "stop_or_escalate"


READ_ONLY_TOOLS = frozenset({
    ToolName.QUERY_TIMING, ToolName.QUERY_CONGESTION, ToolName.QUERY_DRC,
    ToolName.QUERY_POWER, ToolName.QUERY_ARTIFACT_EXCERPT,
    ToolName.COMPARE_RUNS, ToolName.PROPOSE_SEARCH_POLICY,
})


_FORBIDDEN_KEYS = frozenset({
    "command", "shell", "script", "executable", "path", "cwd", "env",
    "environment", "credential", "api_key", "token", "password",
})
_STAGES = frozenset({"synth", "floorplan", "place", "cts", "route", "finish"})
_OPERATORS = frozenset({">=", "<=", "=="})


def _validate_scalar_tree(value: Any, *, field_name: str) -> None:
    """Reject executable/secret fields recursively while accepting JSON data."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise ValueError(f"{field_name} keys must be non-empty strings")
            if key.lower() in _FORBIDDEN_KEYS:
                raise ValueError(f"{field_name} contains forbidden field {key!r}")
            _validate_scalar_tree(item, field_name=field_name)
    elif isinstance(value, (tuple, list)):
        for item in value:
            _validate_scalar_tree(item, field_name=field_name)
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        raise ValueError(f"{field_name} must contain JSON scalar values only")


@dataclass(frozen=True)
class QoRConstraint:
    metric: str
    operator: str
    threshold: float
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        _validate_identifier("metric", self.metric)
        if self.operator not in _OPERATORS:
            raise ValueError("QoRConstraint operator is unsupported")
        if isinstance(self.threshold, bool) or not isinstance(self.threshold, (int, float)):
            raise ValueError("QoRConstraint threshold must be numeric")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "QoRConstraint":
        result = cls(**_known_payload(cls, payload))
        result.validate()
        return result


@dataclass(frozen=True)
class AgentBudget:
    max_eda_runs: int
    max_llm_calls: int
    max_wall_clock_seconds: int
    max_parallel: int = 1
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        for name, value, maximum in (
            ("max_eda_runs", self.max_eda_runs, 100_000),
            ("max_llm_calls", self.max_llm_calls, 100_000),
            ("max_wall_clock_seconds", self.max_wall_clock_seconds, 7 * 86_400),
            ("max_parallel", self.max_parallel, 64),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= maximum:
                raise ValueError(f"{name} is outside agent policy")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AgentBudget":
        result = cls(**_known_payload(cls, payload))
        result.validate()
        return result


@dataclass(frozen=True)
class DesignGoal:
    """Immutable L1 input compiled from natural-language intent.

    The parser may use an LLM, but it must produce this object before it can
    request a tool.  ``allowed_tools`` and the parameter schema are supplied
    by platform policy, not trusted user text.
    """

    goal_id: str
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
    allowed_tools: tuple[ToolName, ...] = tuple(ToolName)
    labels: dict[str, str] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        for name, value in (("goal_id", self.goal_id), ("project_id", self.project_id),
                            ("design_id", self.design_id), ("platform", self.platform),
                            ("pdk_id", self.pdk_id), ("toolchain_id", self.toolchain_id)):
            _validate_identifier(name, value)
        if not isinstance(self.preference, GoalPreference):
            raise ValueError("preference must be a GoalPreference")
        self.rtl_artifact.validate()
        if not self.hard_constraints:
            raise ValueError("DesignGoal requires hard constraints")
        for item in self.hard_constraints:
            item.validate()
        if not self.allowed_stages or any(stage not in _STAGES for stage in self.allowed_stages):
            raise ValueError("DesignGoal has unsupported allowed_stages")
        if len(set(self.allowed_stages)) != len(self.allowed_stages):
            raise ValueError("DesignGoal allowed_stages must be unique")
        if not self.allowed_parameters or any(not IDENTIFIER.fullmatch(item)
                                              for item in self.allowed_parameters):
            raise ValueError("DesignGoal has invalid allowed_parameters")
        if len(set(self.allowed_parameters)) != len(self.allowed_parameters):
            raise ValueError("DesignGoal allowed_parameters must be unique")
        self.budget.validate()
        if min(self.budget.max_eda_runs, self.budget.max_llm_calls,
               self.budget.max_wall_clock_seconds, self.budget.max_parallel) < 1:
            raise ValueError("DesignGoal budget must allocate positive resources")
        if not self.allowed_tools or any(not isinstance(item, ToolName) for item in self.allowed_tools):
            raise ValueError("DesignGoal requires typed allowed_tools")
        if len(set(self.allowed_tools)) != len(self.allowed_tools):
            raise ValueError("DesignGoal allowed_tools must be unique")
        _validate_mapping("labels", self.labels)
        if not all(isinstance(key, str) and isinstance(value, str)
                   for key, value in self.labels.items()):
            raise ValueError("DesignGoal labels must contain strings")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "DesignGoal":
        value = _known_payload(cls, payload)
        value["rtl_artifact"] = EvidencePointer.from_dict(value["rtl_artifact"])
        value["preference"] = GoalPreference(value["preference"])
        value["hard_constraints"] = tuple(QoRConstraint.from_dict(item)
                                            for item in value.get("hard_constraints", ()))
        value["allowed_stages"] = tuple(value.get("allowed_stages", ()))
        value["allowed_parameters"] = tuple(value.get("allowed_parameters", ()))
        value["allowed_tools"] = tuple(ToolName(item) for item in value.get("allowed_tools", ()))
        value["budget"] = AgentBudget.from_dict(value["budget"])
        result = cls(**value)
        result.validate()
        return result


@dataclass(frozen=True)
class DesignState:
    """Immutable evidence-backed state passed to an L1 policy."""

    state_id: str
    goal_id: str
    revision: int
    status: str
    completed_stage: str | None
    metrics: dict[str, float]
    remaining_budget: AgentBudget
    edair_ref: EvidencePointer | None = None
    evidence: tuple[EvidencePointer, ...] = ()
    diagnosis: dict[str, Any] = field(default_factory=dict)
    parent_state_id: str | None = None
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        _validate_identifier("state_id", self.state_id)
        _validate_identifier("goal_id", self.goal_id)
        _validate_identifier("parent_state_id", self.parent_state_id, required=False)
        if not isinstance(self.revision, int) or isinstance(self.revision, bool) or self.revision < 0:
            raise ValueError("DesignState revision must be a non-negative integer")
        if self.status not in {"new", "running", "observed", "failed", "stopped", "completed"}:
            raise ValueError("DesignState status is unsupported")
        if self.completed_stage is not None and self.completed_stage not in _STAGES:
            raise ValueError("DesignState completed_stage is unsupported")
        _validate_mapping("metrics", self.metrics)
        for name, value in self.metrics.items():
            _validate_identifier("metric", name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("DesignState metrics must be numeric")
        self.remaining_budget.validate()
        if self.edair_ref is not None:
            self.edair_ref.validate()
        for item in self.evidence:
            item.validate()
        _validate_mapping("diagnosis", self.diagnosis)
        _validate_scalar_tree(self.diagnosis, field_name="diagnosis")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "DesignState":
        value = _known_payload(cls, payload)
        value["remaining_budget"] = AgentBudget.from_dict(value["remaining_budget"])
        if value.get("edair_ref") is not None:
            value["edair_ref"] = EvidencePointer.from_dict(value["edair_ref"])
        value["evidence"] = tuple(EvidencePointer.from_dict(item)
                                  for item in value.get("evidence", ()))
        result = cls(**value)
        result.validate()
        return result


@dataclass(frozen=True)
class SemanticToolCall:
    call_id: str
    goal_id: str
    state_id: str
    tool: ToolName
    arguments: dict[str, Any]
    producer: str
    evidence: tuple[EvidencePointer, ...] = ()
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        for name, value in (("call_id", self.call_id), ("goal_id", self.goal_id),
                            ("state_id", self.state_id), ("producer", self.producer)):
            _validate_identifier(name, value)
        if not isinstance(self.tool, ToolName):
            raise ValueError("SemanticToolCall tool must be typed")
        _validate_mapping("arguments", self.arguments)
        _validate_scalar_tree(self.arguments, field_name="SemanticToolCall arguments")
        for item in self.evidence:
            item.validate()

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SemanticToolCall":
        value = _known_payload(cls, payload)
        value["tool"] = ToolName(value["tool"])
        value["evidence"] = tuple(EvidencePointer.from_dict(item)
                                  for item in value.get("evidence", ()))
        result = cls(**value)
        result.validate()
        return result


@dataclass(frozen=True)
class ToolReceipt:
    call_id: str
    goal_id: str
    state_id: str
    tool: ToolName
    status: str
    result: dict[str, Any]
    evidence: tuple[EvidencePointer, ...]
    next_state_id: str | None = None
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        for name, value in (("call_id", self.call_id), ("goal_id", self.goal_id),
                            ("state_id", self.state_id)):
            _validate_identifier(name, value)
        _validate_identifier("next_state_id", self.next_state_id, required=False)
        if not isinstance(self.tool, ToolName):
            raise ValueError("ToolReceipt tool must be typed")
        if self.status not in {"accepted", "rejected", "completed", "failed"}:
            raise ValueError("ToolReceipt status is unsupported")
        _validate_mapping("result", self.result)
        _validate_scalar_tree(self.result, field_name="ToolReceipt result")
        if self.status == "completed" and not self.evidence:
            raise ValueError("completed ToolReceipt requires evidence")
        for item in self.evidence:
            item.validate()

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ToolReceipt":
        value = _known_payload(cls, payload)
        value["tool"] = ToolName(value["tool"])
        value["evidence"] = tuple(EvidencePointer.from_dict(item)
                                  for item in value.get("evidence", ()))
        result = cls(**value)
        result.validate()
        return result
