"""Append-only, evidence-aware L1 trace event contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Mapping

from .agent_control import ToolName
from .learning import EvidencePointer
from .l1_tool_contract import reject_forbidden_field_tree
from .platform import SCHEMA_VERSION, _known_payload, _primitive, _validate_identifier, _validate_mapping, _validate_version


class TraceEventKind(str, Enum):
    GOAL_DRAFTED = "goal_drafted"
    GOAL_FINALIZED = "goal_finalized"
    PLAN_PROPOSED = "plan_proposed"
    POLICY_DECIDED = "policy_decided"
    TOOL_CALLED = "tool_called"
    TOOL_RECEIPT = "tool_receipt"
    STATE_TRANSITION = "state_transition"
    REFLECTION_RECORDED = "reflection_recorded"
    STOPPED = "stopped"


_FORBIDDEN_FIELDS = frozenset({
    "command", "shell", "script", "executable", "path", "cwd", "env", "environment",
    "credential", "api_key", "token", "password", "chain_of_thought", "hidden_reasoning",
})


def _json_data(name: str, value: Mapping[str, Any]) -> None:
    reject_forbidden_field_tree(name, value)
    _validate_mapping(name, value)
    for key, item in value.items():
        if isinstance(item, Mapping):
            _json_data(name, item)
        elif isinstance(item, (tuple, list)):
            for child in item:
                if isinstance(child, Mapping):
                    _json_data(name, child)
                elif child is not None and not isinstance(child, (str, int, float, bool)):
                    raise ValueError(f"{name} must contain JSON values")
        elif item is not None and not isinstance(item, (str, int, float, bool)):
            raise ValueError(f"{name} must contain JSON values")


def _digest(name: str, value: str | None, *, required: bool = False) -> None:
    if value is None and not required:
        return
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


@dataclass(frozen=True)
class L1TraceEvent:
    trace_id: str
    event_id: str
    sequence: int
    kind: TraceEventKind
    goal_id: str
    occurred_at: str
    state_before_sha256: str | None
    state_after_sha256: str | None
    planner_summary: str | None
    tool: ToolName | None
    policy_verdict: str | None
    facts: dict[str, Any]
    hypotheses: dict[str, Any]
    evidence: tuple[EvidencePointer, ...]
    parent_event_id: str | None = None
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        for name, value in (("trace_id", self.trace_id), ("event_id", self.event_id), ("goal_id", self.goal_id)):
            _validate_identifier(name, value)
        _validate_identifier("parent_event_id", self.parent_event_id, required=False)
        if not isinstance(self.sequence, int) or isinstance(self.sequence, bool) or self.sequence < 0:
            raise ValueError("trace sequence must be a non-negative integer")
        if not isinstance(self.kind, TraceEventKind):
            raise ValueError("trace event kind must be typed")
        try:
            parsed = datetime.fromisoformat(self.occurred_at.replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise ValueError("trace occurred_at must be ISO-8601") from exc
        if parsed.tzinfo is None:
            raise ValueError("trace occurred_at must include a timezone")
        _digest("state_before_sha256", self.state_before_sha256)
        _digest("state_after_sha256", self.state_after_sha256)
        if (self.state_before_sha256 is None) != (self.state_after_sha256 is None):
            raise ValueError("trace state hashes must be supplied together")
        if self.planner_summary is not None and (not isinstance(self.planner_summary, str) or len(self.planner_summary) > 4000):
            raise ValueError("planner_summary must be bounded text")
        if self.tool is not None and not isinstance(self.tool, ToolName):
            raise ValueError("trace tool must be typed")
        if self.policy_verdict not in {None, "allow", "deny", "needs_clarification"}:
            raise ValueError("trace policy_verdict is unsupported")
        _json_data("facts", self.facts)
        _json_data("hypotheses", self.hypotheses)
        if not isinstance(self.evidence, tuple):
            raise ValueError("trace evidence must be a tuple")
        for item in self.evidence:
            if not isinstance(item, EvidencePointer):
                raise ValueError("trace evidence must contain EvidencePointer values")
            item.validate()
        if self.kind is TraceEventKind.TOOL_RECEIPT and not self.evidence:
            raise ValueError("tool receipt trace requires evidence")
        if self.kind is TraceEventKind.POLICY_DECIDED and self.policy_verdict is None:
            raise ValueError("policy trace requires a verdict")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "L1TraceEvent":
        value = _known_payload(cls, payload)
        value["kind"] = TraceEventKind(value["kind"])
        if value.get("tool") is not None:
            value["tool"] = ToolName(value["tool"])
        value["evidence"] = tuple(EvidencePointer.from_dict(item) for item in value.get("evidence", ()))
        result = cls(**value)
        result.validate()
        return result
