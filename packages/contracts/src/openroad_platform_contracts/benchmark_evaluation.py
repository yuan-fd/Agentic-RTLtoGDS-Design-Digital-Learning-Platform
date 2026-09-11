"""Dependency-free contracts for evidence-backed external benchmark scoring."""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from .learning import EvidencePointer
from .platform import SCHEMA_VERSION, _known_payload, _primitive, _validate_identifier, _validate_version


POSTEDA_TASK_ID = re.compile(r"^(drc_essential|drc_reasoning)/L[123]/q[1-9][0-9]?$" )
ERROR_TYPE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


class DiagnosticDecision(str, Enum):
    INSPECT_DRC_GEOMETRY = "inspect_drc_geometry"
    PROPOSE_BOUNDED_REPAIR = "propose_bounded_repair"
    ABSTAIN = "abstain"


def _task_id(value: Any) -> None:
    if not isinstance(value, str) or not POSTEDA_TASK_ID.fullmatch(value):
        raise ValueError("unsupported PostEDA-Bench task ID")


def _counts(value: Any) -> None:
    if (not isinstance(value, Mapping) or len(value) > 64
            or not all(isinstance(key, str) and ERROR_TYPE.fullmatch(key)
                       and not isinstance(count, bool) and isinstance(count, int)
                       and count >= 0 for key, count in value.items())):
        raise ValueError("error_type_counts must be bounded non-negative counts")


def _evidence(value: Any) -> None:
    if not isinstance(value, tuple) or not value or len(set(value)) != len(value):
        raise ValueError("benchmark prediction requires unique evidence")
    for item in value:
        if not isinstance(item, EvidencePointer):
            raise ValueError("benchmark evidence must contain EvidencePointer values")
        item.validate()


@dataclass(frozen=True)
class PostEDADiagnosisPrediction:
    prediction_id: str
    task_id: str
    error_type_counts: dict[str, int]
    total_errors: int
    decision: DiagnosticDecision
    rationale: str
    evidence: tuple[EvidencePointer, ...]
    hidden_label_accessed: bool = False
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        _validate_identifier("prediction_id", self.prediction_id)
        _task_id(self.task_id)
        _counts(self.error_type_counts)
        if (isinstance(self.total_errors, bool) or not isinstance(self.total_errors, int)
                or self.total_errors < 0
                or self.total_errors != sum(self.error_type_counts.values())):
            raise ValueError("total_errors must equal error_type_counts")
        if not isinstance(self.decision, DiagnosticDecision):
            raise ValueError("diagnostic decision must be typed")
        if (not isinstance(self.rationale, str) or not self.rationale.strip()
                or len(self.rationale) > 2000):
            raise ValueError("diagnostic rationale must be bounded text")
        if self.hidden_label_accessed is not False:
            raise ValueError("a prediction may not access benchmark hidden labels")
        _evidence(self.evidence)

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PostEDADiagnosisPrediction":
        value = _known_payload(cls, payload)
        value["decision"] = DiagnosticDecision(value["decision"])
        value["evidence"] = tuple(EvidencePointer.from_dict(item)
                                  for item in value.get("evidence", ()))
        result = cls(**value)
        result.validate()
        return result


@dataclass(frozen=True)
class PostEDADiagnosisScore:
    evaluation_id: str
    task_id: str
    prediction_id: str
    exact_type_counts: bool
    exact_total_errors: bool
    evidence_grounded: bool
    decision_grounded: bool
    diagnostic_score: float
    official_metric: bool
    notes: tuple[str, ...]
    evidence: tuple[EvidencePointer, ...]
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        _validate_identifier("evaluation_id", self.evaluation_id)
        _validate_identifier("prediction_id", self.prediction_id)
        _task_id(self.task_id)
        for name in ("exact_type_counts", "exact_total_errors",
                     "evidence_grounded", "decision_grounded"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be boolean")
        if (isinstance(self.diagnostic_score, bool)
                or not isinstance(self.diagnostic_score, (int, float))
                or not 0 <= float(self.diagnostic_score) <= 1):
            raise ValueError("diagnostic_score must be between zero and one")
        expected = sum((self.exact_type_counts, self.exact_total_errors,
                        self.evidence_grounded, self.decision_grounded)) / 4
        if abs(float(self.diagnostic_score) - expected) > 1e-12:
            raise ValueError("diagnostic_score does not match its four components")
        if self.official_metric is not False:
            raise ValueError("derived diagnosis score is not an official benchmark metric")
        if (not isinstance(self.notes, tuple) or not self.notes
                or any(not isinstance(item, str) or not item.strip() or len(item) > 1000
                       for item in self.notes)):
            raise ValueError("benchmark score requires bounded notes")
        _evidence(self.evidence)

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PostEDADiagnosisScore":
        value = _known_payload(cls, payload)
        value["notes"] = tuple(value.get("notes", ()))
        value["evidence"] = tuple(EvidencePointer.from_dict(item)
                                  for item in value.get("evidence", ()))
        result = cls(**value)
        result.validate()
        return result
