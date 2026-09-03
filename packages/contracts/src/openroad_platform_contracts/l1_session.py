"""Public, data-only session head for the L1 natural-language control plane."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from .platform import SCHEMA_VERSION, _known_payload, _primitive, _validate_identifier, _validate_version


class L1SessionStatus(str, Enum):
    CREATING = "creating"
    CLARIFICATION_REQUIRED = "clarification_required"
    GOAL_FINALIZED = "goal_finalized"
    FAILED = "failed"


@dataclass(frozen=True)
class L1Session:
    """A durable session head; trace events remain the event authority."""

    session_id: str
    trace_id: str
    project_id: str
    status: L1SessionStatus
    current_draft_id: str | None
    goal_id: str | None
    created_at: str
    updated_at: str
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        for name, value in (("session_id", self.session_id), ("trace_id", self.trace_id),
                            ("project_id", self.project_id)):
            _validate_identifier(name, value)
        _validate_identifier("current_draft_id", self.current_draft_id, required=False)
        _validate_identifier("goal_id", self.goal_id, required=False)
        if not isinstance(self.status, L1SessionStatus):
            raise ValueError("L1 session status must be typed")
        for name, value in (("created_at", self.created_at), ("updated_at", self.updated_at)):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a timestamp")
        if self.status is L1SessionStatus.GOAL_FINALIZED and not self.goal_id:
            raise ValueError("finalized L1 session requires goal_id")

    def to_dict(self) -> dict:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "L1Session":
        value = _known_payload(cls, payload)
        value["status"] = L1SessionStatus(value["status"])
        result = cls(**value)
        result.validate()
        return result
