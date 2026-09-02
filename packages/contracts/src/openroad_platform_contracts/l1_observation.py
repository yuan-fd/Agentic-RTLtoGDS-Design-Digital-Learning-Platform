"""Typed Runtime observation used to advance L1 DesignState."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .learning import EvidencePointer
from .platform import SCHEMA_VERSION, _known_payload, _primitive, _validate_identifier, _validate_mapping, _validate_version


_STAGES = frozenset({"synth", "floorplan", "place", "cts", "route", "finish"})


@dataclass(frozen=True)
class RuntimeObservation:
    run_id: str
    attempt_id: str
    completed_stage: str | None
    terminal_status: str
    metrics: dict[str, float]
    evidence: tuple[EvidencePointer, ...]
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        _validate_identifier("run_id", self.run_id)
        _validate_identifier("attempt_id", self.attempt_id)
        if self.completed_stage is not None and self.completed_stage not in _STAGES:
            raise ValueError("observation completed_stage is unsupported")
        if self.terminal_status not in {"succeeded", "failed", "cancelled", "timed_out", "lost"}:
            raise ValueError("observation terminal_status is unsupported")
        _validate_mapping("observation metrics", self.metrics)
        for name, value in self.metrics.items():
            _validate_identifier("metric", name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("observation metrics must be numeric")
        if not isinstance(self.evidence, tuple) or not self.evidence:
            raise ValueError("Runtime observation requires evidence")
        for item in self.evidence:
            if not isinstance(item, EvidencePointer):
                raise ValueError("observation evidence must contain EvidencePointer values")
            item.validate()

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RuntimeObservation":
        value = _known_payload(cls, payload)
        value["evidence"] = tuple(EvidencePointer.from_dict(item) for item in value.get("evidence", ()))
        result = cls(**value)
        result.validate()
        return result
