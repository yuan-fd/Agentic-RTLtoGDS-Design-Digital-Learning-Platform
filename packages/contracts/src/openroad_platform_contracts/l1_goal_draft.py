"""Dependency-free L1 natural-language draft and clarification contracts.

These contracts retain what a language model (or deterministic parser) has
understood, but intentionally cannot authorize a tool or construct a final
``DesignGoal`` on their own.  Platform policy supplies the verified design,
toolchain, protected assets, allowlists, and final budget later.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from typing import Any, Mapping

from .platform import SCHEMA_VERSION, _known_payload, _primitive, _validate_identifier, _validate_version


class GoalIntent(str, Enum):
    DIAGNOSE = "diagnose"
    EXECUTE = "execute"
    OPTIMIZE = "optimize"
    COMPARE = "compare"
    EXPLAIN = "explain"


class ClarificationField(str, Enum):
    DESIGN_CONTEXT = "design_context"
    TOOLCHAIN = "toolchain"
    OBJECTIVE = "objective"
    CONSTRAINTS = "constraints"
    CHANGE_SCOPE = "change_scope"
    BUDGET = "budget"


def _text(name: str, value: Any, *, maximum: int) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{name} must be non-empty text up to {maximum} characters")


@dataclass(frozen=True)
class ClarificationQuestion:
    question_id: str
    field: ClarificationField
    prompt: str
    blocking: bool = True
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        _validate_identifier("question_id", self.question_id)
        if not isinstance(self.field, ClarificationField):
            raise ValueError("clarification field must be typed")
        _text("clarification prompt", self.prompt, maximum=2000)
        if not isinstance(self.blocking, bool):
            raise ValueError("clarification blocking must be boolean")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ClarificationQuestion":
        value = _known_payload(cls, payload)
        value["field"] = ClarificationField(value["field"])
        result = cls(**value)
        result.validate()
        return result


@dataclass(frozen=True)
class ClarificationAnswer:
    question_id: str
    field: ClarificationField
    value: str
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        _validate_identifier("question_id", self.question_id)
        if not isinstance(self.field, ClarificationField):
            raise ValueError("clarification answer field must be typed")
        _text("clarification answer", self.value, maximum=4000)

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ClarificationAnswer":
        value = _known_payload(cls, payload)
        value["field"] = ClarificationField(value["field"])
        result = cls(**value)
        result.validate()
        return result


@dataclass(frozen=True)
class GoalDraft:
    """Untrusted language interpretation with explicit unresolved questions."""

    draft_id: str
    request_text: str
    intent: GoalIntent
    questions: tuple[ClarificationQuestion, ...] = ()
    answers: tuple[ClarificationAnswer, ...] = ()
    parser_id: str = "deterministic"
    schema_version: int = SCHEMA_VERSION

    @property
    def request_sha256(self) -> str:
        return sha256(self.request_text.encode("utf-8")).hexdigest()

    def unresolved_blocking_fields(self) -> tuple[ClarificationField, ...]:
        answered = {item.question_id for item in self.answers}
        return tuple(item.field for item in self.questions if item.blocking and item.question_id not in answered)

    def validate(self) -> None:
        _validate_version(self.schema_version)
        _validate_identifier("draft_id", self.draft_id)
        _validate_identifier("parser_id", self.parser_id)
        _text("request_text", self.request_text, maximum=8000)
        if not isinstance(self.intent, GoalIntent):
            raise ValueError("goal draft intent must be typed")
        for item in self.questions:
            item.validate()
        if len({item.question_id for item in self.questions}) != len(self.questions):
            raise ValueError("goal draft question ids must be unique")
        known = {item.question_id: item.field for item in self.questions}
        for item in self.answers:
            item.validate()
            if known.get(item.question_id) is not item.field:
                raise ValueError("clarification answer does not match a draft question")
        if len({item.question_id for item in self.answers}) != len(self.answers):
            raise ValueError("goal draft answers must be unique")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GoalDraft":
        value = _known_payload(cls, payload)
        value["intent"] = GoalIntent(value["intent"])
        value["questions"] = tuple(ClarificationQuestion.from_dict(item)
                                   for item in value.get("questions", ()))
        value["answers"] = tuple(ClarificationAnswer.from_dict(item)
                                 for item in value.get("answers", ()))
        result = cls(**value)
        result.validate()
        return result
