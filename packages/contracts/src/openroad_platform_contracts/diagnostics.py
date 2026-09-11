"""Dependency-free contracts for evidence-backed deterministic diagnosis."""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from .learning import EvidencePointer
from .platform import (
    IDENTIFIER, SCHEMA_VERSION, _known_payload, _primitive,
    _validate_identifier, _validate_version,
)


class AnalysisDomain(str, Enum):
    TIMING = "timing"
    CONGESTION = "congestion"
    DRC = "drc"
    POWER = "power"


class AnalysisCompleteness(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


def _text(name: str, value: Any, *, maximum: int = 2000) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{name} must be bounded non-empty text")


def _number(name: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _evidence(values: tuple[EvidencePointer, ...], *, required: bool = True) -> None:
    if not isinstance(values, tuple) or (required and not values):
        raise ValueError("evidence must be a non-empty tuple")
    if len(set(values)) != len(values):
        raise ValueError("evidence must not contain duplicates")
    for item in values:
        if not isinstance(item, EvidencePointer):
            raise ValueError("evidence must contain EvidencePointer values")
        item.validate()


def _ids(name: str, values: tuple[str, ...], *, required: bool = False) -> None:
    if not isinstance(values, tuple) or (required and not values):
        raise ValueError(f"{name} must be a tuple")
    if len(set(values)) != len(values):
        raise ValueError(f"{name} must be unique")
    for item in values:
        _validate_identifier(name, item)


@dataclass(frozen=True)
class MetricFact:
    fact_id: str
    domain: AnalysisDomain
    stage: str
    metric: str
    value: float
    unit: str
    authority: str
    evidence: tuple[EvidencePointer, ...]
    parser_id: str | None = None
    parser_version: str | None = None
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        _validate_identifier("fact_id", self.fact_id)
        if not isinstance(self.domain, AnalysisDomain):
            raise ValueError("metric fact domain must be typed")
        for name, value in (("stage", self.stage), ("metric", self.metric)):
            _validate_identifier(name, value)
        _number("metric value", self.value)
        _text("metric unit", self.unit, maximum=64)
        if self.authority not in {"runtime_metric", "protected_evaluator"}:
            raise ValueError("metric authority is unsupported")
        for name, value in (("parser_id", self.parser_id),
                            ("parser_version", self.parser_version)):
            if value is not None:
                _validate_identifier(name, value)
        if self.authority == "runtime_metric" and not self.parser_id:
            raise ValueError("Runtime metric fact requires parser identity")
        _evidence(self.evidence)

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MetricFact":
        value = _known_payload(cls, payload)
        value["domain"] = AnalysisDomain(value["domain"])
        value["evidence"] = tuple(EvidencePointer.from_dict(item)
                                  for item in value.get("evidence", ()))
        result = cls(**value)
        result.validate()
        return result


@dataclass(frozen=True)
class AnalysisTarget:
    metric: str
    operator: str
    threshold: float
    unit: str
    evidence: tuple[EvidencePointer, ...]
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        _validate_identifier("target metric", self.metric)
        if self.operator not in {">=", "<=", "=="}:
            raise ValueError("target operator is unsupported")
        _number("target threshold", self.threshold)
        _text("target unit", self.unit, maximum=64)
        _evidence(self.evidence)

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AnalysisTarget":
        value = _known_payload(cls, payload)
        value["evidence"] = tuple(EvidencePointer.from_dict(item)
                                  for item in value.get("evidence", ()))
        result = cls(**value)
        result.validate()
        return result


@dataclass(frozen=True)
class Headroom:
    metric: str
    operator: str
    observed: float
    threshold: float
    margin: float
    unit: str
    status: str
    evidence: tuple[EvidencePointer, ...]
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        _validate_identifier("headroom metric", self.metric)
        if self.operator not in {">=", "<=", "=="}:
            raise ValueError("headroom operator is unsupported")
        observed = _number("headroom observed", self.observed)
        threshold = _number("headroom threshold", self.threshold)
        margin = _number("headroom margin", self.margin)
        expected = (observed - threshold if self.operator == ">=" else
                    threshold - observed if self.operator == "<=" else
                    -abs(observed - threshold))
        if not math.isclose(margin, expected, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("headroom margin does not match operator semantics")
        expected_status = "satisfied" if margin >= 0 else "violated"
        if self.status != expected_status:
            raise ValueError("headroom status does not match its margin")
        _text("headroom unit", self.unit, maximum=64)
        _evidence(self.evidence)

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Headroom":
        value = _known_payload(cls, payload)
        value["evidence"] = tuple(EvidencePointer.from_dict(item)
                                  for item in value.get("evidence", ()))
        result = cls(**value)
        result.validate()
        return result


@dataclass(frozen=True)
class DiagnosticStatement:
    statement_id: str
    statement: str
    basis_fact_ids: tuple[str, ...]
    verification_checks: tuple[str, ...]
    evidence: tuple[EvidencePointer, ...]
    status: str = "unconfirmed"
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        _validate_identifier("statement_id", self.statement_id)
        _text("diagnostic statement", self.statement)
        _ids("basis_fact_ids", self.basis_fact_ids, required=True)
        if (not isinstance(self.verification_checks, tuple)
                or not self.verification_checks):
            raise ValueError("diagnostic statement requires verification checks")
        for item in self.verification_checks:
            _text("verification check", item)
        if self.status not in {"unconfirmed", "counter_evidence"}:
            raise ValueError("diagnostic statement status is unsupported")
        _evidence(self.evidence)

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "DiagnosticStatement":
        value = _known_payload(cls, payload)
        for name in ("basis_fact_ids", "verification_checks"):
            value[name] = tuple(value.get(name, ()))
        value["evidence"] = tuple(EvidencePointer.from_dict(item)
                                  for item in value.get("evidence", ()))
        result = cls(**value)
        result.validate()
        return result


@dataclass(frozen=True)
class StageAnalysis:
    analysis_id: str
    run_id: str
    attempt_id: str
    domain: AnalysisDomain
    stage: str
    completeness: AnalysisCompleteness
    facts: tuple[MetricFact, ...]
    headroom: tuple[Headroom, ...]
    blockers: tuple[str, ...]
    unknowns: tuple[str, ...]
    evidence: tuple[EvidencePointer, ...]
    analyzer_id: str = "deterministic-stage-analyzer-v1"
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        for name, value in (("analysis_id", self.analysis_id),
                            ("run_id", self.run_id),
                            ("attempt_id", self.attempt_id),
                            ("stage", self.stage),
                            ("analyzer_id", self.analyzer_id)):
            _validate_identifier(name, value)
        if not isinstance(self.domain, AnalysisDomain):
            raise ValueError("analysis domain must be typed")
        if not isinstance(self.completeness, AnalysisCompleteness):
            raise ValueError("analysis completeness must be typed")
        if self.completeness is AnalysisCompleteness.UNAVAILABLE and self.facts:
            raise ValueError("unavailable analysis cannot contain metric facts")
        if self.completeness is not AnalysisCompleteness.UNAVAILABLE and not self.facts:
            raise ValueError("available analysis requires metric facts")
        for fact in self.facts:
            fact.validate()
            if fact.domain is not self.domain:
                raise ValueError("analysis contains a fact from another domain")
        for item in self.headroom:
            item.validate()
            if item.metric not in {fact.metric for fact in self.facts}:
                raise ValueError("headroom requires an observed metric fact")
        _ids("blockers", self.blockers)
        if not isinstance(self.unknowns, tuple):
            raise ValueError("unknowns must be a tuple")
        for item in self.unknowns:
            _text("analysis unknown", item)
        _evidence(self.evidence)

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "StageAnalysis":
        value = _known_payload(cls, payload)
        value["domain"] = AnalysisDomain(value["domain"])
        value["completeness"] = AnalysisCompleteness(value["completeness"])
        value["facts"] = tuple(MetricFact.from_dict(item)
                               for item in value.get("facts", ()))
        value["headroom"] = tuple(Headroom.from_dict(item)
                                  for item in value.get("headroom", ()))
        for name in ("blockers", "unknowns"):
            value[name] = tuple(value.get(name, ()))
        value["evidence"] = tuple(EvidencePointer.from_dict(item)
                                  for item in value.get("evidence", ()))
        result = cls(**value)
        result.validate()
        return result


@dataclass(frozen=True)
class DiagnosisReport:
    report_id: str
    run_id: str
    analyses: tuple[StageAnalysis, ...]
    hypotheses: tuple[DiagnosticStatement, ...]
    counter_evidence: tuple[DiagnosticStatement, ...]
    blockers: tuple[str, ...]
    unknowns: tuple[str, ...]
    next_checks: tuple[str, ...]
    evidence: tuple[EvidencePointer, ...]
    analyzer_id: str = "deterministic-diagnosis-v1"
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        for name, value in (("report_id", self.report_id),
                            ("run_id", self.run_id),
                            ("analyzer_id", self.analyzer_id)):
            _validate_identifier(name, value)
        if (not isinstance(self.analyses, tuple) or len(self.analyses) != 4
                or {item.domain for item in self.analyses} != set(AnalysisDomain)):
            raise ValueError("diagnosis requires exactly four domain analyses")
        fact_ids = set()
        for item in self.analyses:
            item.validate()
            if item.run_id != self.run_id:
                raise ValueError("diagnosis analyses must bind one Runtime run")
            fact_ids.update(fact.fact_id for fact in item.facts)
        for item in self.hypotheses:
            item.validate()
            if item.status != "unconfirmed" or not set(item.basis_fact_ids) <= fact_ids:
                raise ValueError("hypothesis basis is invalid")
        for item in self.counter_evidence:
            item.validate()
            if item.status != "counter_evidence" or not set(item.basis_fact_ids) <= fact_ids:
                raise ValueError("counter-evidence basis is invalid")
        _ids("blockers", self.blockers)
        for name, values in (("unknowns", self.unknowns),
                             ("next_checks", self.next_checks)):
            if not isinstance(values, tuple):
                raise ValueError(f"{name} must be a tuple")
            for item in values:
                _text(name, item)
        _evidence(self.evidence)

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "DiagnosisReport":
        value = _known_payload(cls, payload)
        value["analyses"] = tuple(StageAnalysis.from_dict(item)
                                   for item in value.get("analyses", ()))
        value["hypotheses"] = tuple(DiagnosticStatement.from_dict(item)
                                     for item in value.get("hypotheses", ()))
        value["counter_evidence"] = tuple(DiagnosticStatement.from_dict(item)
                                          for item in value.get("counter_evidence", ()))
        for name in ("blockers", "unknowns", "next_checks"):
            value[name] = tuple(value.get(name, ()))
        value["evidence"] = tuple(EvidencePointer.from_dict(item)
                                  for item in value.get("evidence", ()))
        result = cls(**value)
        result.validate()
        return result
