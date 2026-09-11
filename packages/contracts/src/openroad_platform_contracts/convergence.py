"""Evidence-backed metric trajectory and convergence assessment contracts.

These types describe observations and deterministic conclusions only.  They
cannot execute a recovery action or select optimization parameters.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from .l1_control_state import ConvergenceState
from .learning import EvidencePointer, SHA256
from .platform import (
    SCHEMA_VERSION, _known_payload, _primitive, _validate_identifier,
    _validate_version,
)


class ObjectiveDirection(str, Enum):
    MAXIMIZE = "maximize"
    MINIMIZE = "minimize"


def _number(name: str, value: Any, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or (nonnegative and result < 0):
        raise ValueError(f"{name} must be finite" +
                         (" and non-negative" if nonnegative else ""))
    return result


def _evidence(values: tuple[EvidencePointer, ...]) -> None:
    if not isinstance(values, tuple) or not values or len(set(values)) != len(values):
        raise ValueError("convergence evidence must be a unique non-empty tuple")
    for item in values:
        if not isinstance(item, EvidencePointer):
            raise ValueError("convergence evidence must be typed")
        item.validate()


@dataclass(frozen=True)
class MetricTrajectoryPoint:
    point_id: str
    sequence_index: int
    run_id: str
    attempt_id: str
    stage: str
    metric: str
    unit: str
    terminal_status: str
    protocol_sha256: str
    authority: str
    evidence: tuple[EvidencePointer, ...]
    value: float | None = None
    failure_category: str | None = None
    parser_id: str | None = None
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        for name, value in (("point_id", self.point_id), ("run_id", self.run_id),
                            ("attempt_id", self.attempt_id), ("stage", self.stage),
                            ("metric", self.metric)):
            _validate_identifier(name, value)
        if (not isinstance(self.sequence_index, int) or isinstance(self.sequence_index, bool)
                or self.sequence_index < 0):
            raise ValueError("trajectory sequence index must be non-negative")
        if not isinstance(self.unit, str) or not self.unit or len(self.unit) > 64:
            raise ValueError("trajectory unit must be bounded text")
        if self.terminal_status not in {
            "succeeded", "failed", "cancelled", "timed_out", "lost",
        }:
            raise ValueError("trajectory terminal status is unsupported")
        if not isinstance(self.protocol_sha256, str) or not SHA256.fullmatch(
                self.protocol_sha256):
            raise ValueError("trajectory point requires a protocol SHA-256")
        if self.authority not in {"protected_evaluator", "runtime_metric"}:
            raise ValueError("trajectory authority is unsupported")
        if self.authority == "runtime_metric" and not self.parser_id:
            raise ValueError("Runtime metric trajectory point requires parser identity")
        if self.parser_id is not None:
            _validate_identifier("parser_id", self.parser_id)
        if self.terminal_status == "succeeded":
            _number("trajectory value", self.value)
            if self.failure_category is not None:
                raise ValueError("successful trajectory point cannot carry a failure")
        else:
            if self.value is not None:
                raise ValueError("failed trajectory point cannot carry a measured value")
            _validate_identifier("failure_category", self.failure_category)
        _evidence(self.evidence)

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MetricTrajectoryPoint":
        value = _known_payload(cls, payload)
        value["evidence"] = tuple(EvidencePointer.from_dict(item)
                                  for item in value.get("evidence", ()))
        result = cls(**value)
        result.validate()
        return result


@dataclass(frozen=True)
class MetricTrajectory:
    trajectory_id: str
    metric: str
    unit: str
    direction: ObjectiveDirection
    protocol_sha256: str
    points: tuple[MetricTrajectoryPoint, ...]
    evidence: tuple[EvidencePointer, ...]
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        _validate_identifier("trajectory_id", self.trajectory_id)
        _validate_identifier("metric", self.metric)
        if not isinstance(self.unit, str) or not self.unit or len(self.unit) > 64:
            raise ValueError("trajectory unit must be bounded text")
        if not isinstance(self.direction, ObjectiveDirection):
            raise ValueError("trajectory direction must be typed")
        if not isinstance(self.protocol_sha256, str) or not SHA256.fullmatch(
                self.protocol_sha256):
            raise ValueError("trajectory requires a protocol SHA-256")
        if not isinstance(self.points, tuple) or not self.points:
            raise ValueError("trajectory requires points")
        if len({item.point_id for item in self.points}) != len(self.points):
            raise ValueError("trajectory point ids must be unique")
        previous = -1
        for item in self.points:
            item.validate()
            if item.sequence_index <= previous:
                raise ValueError("trajectory points must be strictly ordered")
            previous = item.sequence_index
            if (item.metric, item.unit, item.protocol_sha256) != (
                    self.metric, self.unit, self.protocol_sha256):
                raise ValueError("trajectory points are not comparable")
        _evidence(self.evidence)

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MetricTrajectory":
        value = _known_payload(cls, payload)
        value["direction"] = ObjectiveDirection(value["direction"])
        value["points"] = tuple(MetricTrajectoryPoint.from_dict(item)
                                for item in value.get("points", ()))
        value["evidence"] = tuple(EvidencePointer.from_dict(item)
                                  for item in value.get("evidence", ()))
        result = cls(**value)
        result.validate()
        return result


@dataclass(frozen=True)
class ConvergencePolicy:
    policy_id: str
    absolute_tolerance: float
    relative_tolerance: float
    stall_window: int = 3
    divergence_window: int = 3
    minimum_successful_points: int = 2
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        _validate_identifier("policy_id", self.policy_id)
        _number("absolute_tolerance", self.absolute_tolerance, nonnegative=True)
        relative = _number("relative_tolerance", self.relative_tolerance,
                           nonnegative=True)
        if relative > 1:
            raise ValueError("relative tolerance must be at most one")
        for name, value in (("stall_window", self.stall_window),
                            ("divergence_window", self.divergence_window),
                            ("minimum_successful_points", self.minimum_successful_points)):
            if (not isinstance(value, int) or isinstance(value, bool)
                    or not 2 <= value <= 100):
                raise ValueError(f"{name} must be between 2 and 100")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ConvergencePolicy":
        result = cls(**_known_payload(cls, payload))
        result.validate()
        return result


@dataclass(frozen=True)
class ConvergenceAssessment:
    assessment_id: str
    trajectory_id: str
    policy_id: str
    state: ConvergenceState
    reason_code: str
    considered_point_ids: tuple[str, ...]
    signed_benefit_deltas: tuple[float, ...]
    transition_tolerances: tuple[float, ...]
    evidence: tuple[EvidencePointer, ...]
    classifier_id: str = "deterministic-convergence-v1"
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        for name, value in (("assessment_id", self.assessment_id),
                            ("trajectory_id", self.trajectory_id),
                            ("policy_id", self.policy_id),
                            ("reason_code", self.reason_code),
                            ("classifier_id", self.classifier_id)):
            _validate_identifier(name, value)
        if not isinstance(self.state, ConvergenceState):
            raise ValueError("convergence assessment state must be typed")
        if (not isinstance(self.considered_point_ids, tuple)
                or not self.considered_point_ids
                or len(set(self.considered_point_ids)) != len(self.considered_point_ids)):
            raise ValueError("assessment requires unique considered points")
        for item in self.considered_point_ids:
            _validate_identifier("considered point", item)
        if len(self.signed_benefit_deltas) != len(self.transition_tolerances):
            raise ValueError("assessment transition vectors must align")
        for item in self.signed_benefit_deltas:
            _number("signed benefit delta", item)
        for item in self.transition_tolerances:
            _number("transition tolerance", item, nonnegative=True)
        _evidence(self.evidence)

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ConvergenceAssessment":
        value = _known_payload(cls, payload)
        value["state"] = ConvergenceState(value["state"])
        for name in ("considered_point_ids", "signed_benefit_deltas",
                     "transition_tolerances"):
            value[name] = tuple(value.get(name, ()))
        value["evidence"] = tuple(EvidencePointer.from_dict(item)
                                  for item in value.get("evidence", ()))
        result = cls(**value)
        result.validate()
        return result
