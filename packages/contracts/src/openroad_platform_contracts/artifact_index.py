"""Typed cross-artifact graph contracts with artifact/file-line citations."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from .learning import EvidencePointer
from .platform import (
    SCHEMA_VERSION, _known_payload, _primitive, _validate_identifier,
    _validate_version,
)


class ArtifactEntityKind(str, Enum):
    RTL = "rtl"
    CONFIG = "config"
    LOG = "log"
    REPORT = "report"
    METRIC = "metric"
    STAGE = "stage"
    ARTIFACT = "artifact"


class ArtifactRelation(str, Enum):
    STAGE_PRODUCED = "stage_produced"
    METRIC_DERIVED_FROM = "metric_derived_from"
    CO_REGISTERED = "co_registered"
    CONTENT_MATCH = "content_match"


def _text(name: str, value: Any, *, maximum: int = 1000) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{name} must be bounded non-empty text")


def _evidence(values: tuple[EvidencePointer, ...]) -> None:
    if not isinstance(values, tuple) or not values or len(set(values)) != len(values):
        raise ValueError("index evidence must be a unique non-empty tuple")
    for item in values:
        item.validate()


@dataclass(frozen=True)
class ArtifactIndexNode:
    node_id: str
    entity_kind: ArtifactEntityKind
    run_id: str
    stage: str
    label: str
    evidence: tuple[EvidencePointer, ...]
    artifact_id: str | None = None
    artifact_kind: str | None = None
    metric_name: str | None = None
    metric_value: float | None = None
    metric_unit: str | None = None
    document_name: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    location_precision: str | None = None
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        for name, value, required in (
            ("node_id", self.node_id, True), ("run_id", self.run_id, True),
            ("stage", self.stage, True), ("artifact_id", self.artifact_id, False),
            ("artifact_kind", self.artifact_kind, False),
            ("metric_name", self.metric_name, False),
        ):
            _validate_identifier(name, value, required=required)
        if not isinstance(self.entity_kind, ArtifactEntityKind):
            raise ValueError("artifact entity kind must be typed")
        _text("node label", self.label)
        _evidence(self.evidence)
        if self.entity_kind is ArtifactEntityKind.STAGE:
            if any(value is not None for value in (
                    self.artifact_id, self.artifact_kind, self.metric_name,
                    self.metric_value, self.metric_unit, self.document_name, self.line_start,
                    self.line_end, self.location_precision)):
                raise ValueError("stage node cannot forge artifact or metric fields")
        if self.entity_kind is ArtifactEntityKind.METRIC:
            if (not self.metric_name or self.metric_value is None
                    or isinstance(self.metric_value, bool)
                    or not isinstance(self.metric_value, (int, float))
                    or not math.isfinite(float(self.metric_value))):
                raise ValueError("metric node requires a finite typed metric")
            _text("metric unit", self.metric_unit, maximum=64)
        elif self.metric_name is not None or self.metric_value is not None or self.metric_unit is not None:
            raise ValueError("only metric nodes may carry metric fields")
        if self.document_name is not None:
            _text("document name", self.document_name, maximum=255)
            if "/" in self.document_name or "\\" in self.document_name or self.document_name in {".", ".."}:
                raise ValueError("document name must be a basename, not a path")
        located = (self.line_start, self.line_end, self.location_precision)
        if any(value is not None for value in located):
            if (not self.document_name or not isinstance(self.line_start, int)
                    or isinstance(self.line_start, bool)
                    or not isinstance(self.line_end, int) or isinstance(self.line_end, bool)
                    or self.line_start < 1 or self.line_end < self.line_start
                    or self.location_precision not in {"exact_line", "whole_excerpt"}):
                raise ValueError("artifact location is invalid")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ArtifactIndexNode":
        value = _known_payload(cls, payload)
        value["entity_kind"] = ArtifactEntityKind(value["entity_kind"])
        value["evidence"] = tuple(EvidencePointer.from_dict(item)
                                  for item in value.get("evidence", ()))
        result = cls(**value)
        result.validate()
        return result


@dataclass(frozen=True)
class ArtifactIndexEdge:
    edge_id: str
    relation: ArtifactRelation
    source_node_id: str
    target_node_id: str
    evidence: tuple[EvidencePointer, ...]
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        for name, value in (("edge_id", self.edge_id),
                            ("source_node_id", self.source_node_id),
                            ("target_node_id", self.target_node_id)):
            _validate_identifier(name, value)
        if self.source_node_id == self.target_node_id:
            raise ValueError("artifact graph self-edge is invalid")
        if not isinstance(self.relation, ArtifactRelation):
            raise ValueError("artifact relation must be typed")
        _evidence(self.evidence)

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ArtifactIndexEdge":
        value = _known_payload(cls, payload)
        value["relation"] = ArtifactRelation(value["relation"])
        value["evidence"] = tuple(EvidencePointer.from_dict(item)
                                  for item in value.get("evidence", ()))
        result = cls(**value)
        result.validate()
        return result


@dataclass(frozen=True)
class CrossArtifactIndex:
    index_id: str
    scope_id: str
    run_ids: tuple[str, ...]
    nodes: tuple[ArtifactIndexNode, ...]
    edges: tuple[ArtifactIndexEdge, ...]
    unknowns: tuple[str, ...]
    evidence: tuple[EvidencePointer, ...]
    indexer_id: str = "runtime-artifact-graph-v1"
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        for name, value in (("index_id", self.index_id), ("scope_id", self.scope_id),
                            ("indexer_id", self.indexer_id)):
            _validate_identifier(name, value)
        if (not isinstance(self.run_ids, tuple) or not self.run_ids
                or len(set(self.run_ids)) != len(self.run_ids)):
            raise ValueError("cross-artifact index requires unique Runtime runs")
        for run_id in self.run_ids:
            _validate_identifier("run_id", run_id)
        if not isinstance(self.nodes, tuple) or not self.nodes:
            raise ValueError("cross-artifact index requires nodes")
        node_ids = set()
        for item in self.nodes:
            item.validate()
            if item.run_id not in self.run_ids or item.node_id in node_ids:
                raise ValueError("index node run or identity is invalid")
            node_ids.add(item.node_id)
        edge_ids = set()
        for item in self.edges:
            item.validate()
            if (item.edge_id in edge_ids or item.source_node_id not in node_ids
                    or item.target_node_id not in node_ids):
                raise ValueError("index edge identity or endpoint is invalid")
            edge_ids.add(item.edge_id)
        if not isinstance(self.unknowns, tuple):
            raise ValueError("index unknowns must be a tuple")
        for item in self.unknowns:
            _text("index unknown", item)
        _evidence(self.evidence)

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CrossArtifactIndex":
        value = _known_payload(cls, payload)
        value["run_ids"] = tuple(value.get("run_ids", ()))
        value["nodes"] = tuple(ArtifactIndexNode.from_dict(item)
                               for item in value.get("nodes", ()))
        value["edges"] = tuple(ArtifactIndexEdge.from_dict(item)
                               for item in value.get("edges", ()))
        value["unknowns"] = tuple(value.get("unknowns", ()))
        value["evidence"] = tuple(EvidencePointer.from_dict(item)
                                  for item in value.get("evidence", ()))
        result = cls(**value)
        result.validate()
        return result
