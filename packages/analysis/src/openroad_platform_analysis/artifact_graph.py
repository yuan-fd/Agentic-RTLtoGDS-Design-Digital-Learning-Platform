"""Build a bounded EDATracer-style typed graph from Runtime records."""

from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
from typing import Any, Callable, Mapping, Sequence

from openroad_platform_contracts import (
    ArtifactEntityKind, ArtifactIndexEdge, ArtifactIndexNode,
    ArtifactRelation, CrossArtifactIndex, EvidencePointer,
)


ArtifactReader = Callable[..., Mapping[str, Any]]


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str,
    ).encode()).hexdigest()


def _id(prefix: str, value: Any) -> str:
    return f"{prefix}-{_digest(value)[:20]}"


def _artifact_pointer(value: Mapping[str, Any]) -> EvidencePointer:
    artifact_id, sha256 = value.get("artifact_id"), value.get("sha256")
    if (not isinstance(artifact_id, str) or not artifact_id
            or not isinstance(sha256, str) or len(sha256) != 64):
        raise ValueError("registered artifact lacks identity or SHA-256")
    return EvidencePointer(f"artifact:runtime-{artifact_id}", sha256)


def _run_pointer(view: Mapping[str, Any]) -> EvidencePointer:
    run = view["run"]
    return EvidencePointer(f"run:{run['run_id']}", _digest({
        "run_id": run["run_id"], "status": run.get("status"),
        "task_id": run.get("task_id"),
    }))


def _entity(kind: str) -> ArtifactEntityKind:
    if kind in {"rtl", "rtl_candidate", "netlist"}:
        return ArtifactEntityKind.RTL
    if kind in {"config", "sdc", "parameter_contract", "design_input_manifest",
                "toolchain_snapshot"}:
        return ArtifactEntityKind.CONFIG
    if kind == "log":
        return ArtifactEntityKind.LOG
    if kind in {"report", "run_result", "simulation_report", "mutation_report",
                "verification_report", "rtlscout_result"}:
        return ArtifactEntityKind.REPORT
    return ArtifactEntityKind.ARTIFACT


def _physical_stage(name: str, fallback: str) -> str:
    prefix = name.split("_", 1)[0]
    return {"1": "synth", "2": "floorplan", "3": "place", "4": "cts",
            "5": "route", "6": "finish"}.get(prefix, fallback)


def _line_for(text: str | None, needle: str) -> int | None:
    if text is None:
        return None
    return next((index for index, line in enumerate(text.splitlines(), 1)
                 if needle in line), None)


def build_cross_artifact_index(
    runtime_views: Sequence[Mapping[str, Any]], *, scope_id: str,
    artifact_reader: ArtifactReader | None = None,
    max_excerpt_bytes: int = 64 * 1024,
) -> CrossArtifactIndex:
    """Index registered facts; optional content is read only through Runtime."""
    if (not isinstance(max_excerpt_bytes, int) or isinstance(max_excerpt_bytes, bool)
            or not 1 <= max_excerpt_bytes <= 64 * 1024):
        raise ValueError("artifact index excerpt bound is invalid")
    nodes: list[ArtifactIndexNode] = []
    edges: list[ArtifactIndexEdge] = []
    unknowns: list[str] = []
    run_ids = []
    stage_nodes: dict[tuple[str, str], ArtifactIndexNode] = {}
    artifact_nodes: dict[tuple[str, str], ArtifactIndexNode] = {}
    content_by_artifact: dict[tuple[str, str], str] = {}
    hashes: dict[str, list[ArtifactIndexNode]] = {}

    def stage_node(run_id: str, stage: str, evidence: EvidencePointer) -> ArtifactIndexNode:
        key = (run_id, stage)
        if key not in stage_nodes:
            node = ArtifactIndexNode(
                _id("node", (run_id, "stage", stage)), ArtifactEntityKind.STAGE,
                run_id, stage, f"Runtime stage {stage}", (evidence,),
            )
            node.validate(); stage_nodes[key] = node; nodes.append(node)
        return stage_nodes[key]

    for view in runtime_views:
        run = view.get("run")
        if not isinstance(run, Mapping) or not isinstance(run.get("run_id"), str):
            raise ValueError("artifact graph requires Runtime describe views")
        run_id = run["run_id"]
        if run_id in run_ids:
            raise ValueError("artifact graph Runtime runs must be unique")
        run_ids.append(run_id)
        run_evidence = _run_pointer(view)
        for event in view.get("events", ()):
            if event.get("event_type") in {"tool.stage.started", "tool.stage.finished"}:
                physical = (event.get("payload") or {}).get("tool_stage")
                if isinstance(physical, str):
                    stage_node(run_id, physical, run_evidence)
        for stage in view.get("stages", ()):
            stage_name = str(stage.get("stage_key") or "unknown_stage")
            execution_stage = stage_node(run_id, stage_name, run_evidence)
            for attempt in stage.get("attempts", ()):
                attempt_artifacts = []
                for artifact in attempt.get("artifacts", ()):
                    artifact_id = artifact.get("artifact_id")
                    kind = artifact.get("kind")
                    store_key = artifact.get("store_key")
                    if (not isinstance(artifact_id, str) or not artifact_id
                            or not isinstance(kind, str) or not kind
                            or not isinstance(store_key, str) or not store_key):
                        unknowns.append(
                            f"Run {run_id} contains an artifact without indexable identity metadata.")
                        continue
                    evidence = _artifact_pointer(artifact)
                    document = PurePosixPath(store_key).name
                    artifact_stage = _physical_stage(document, stage_name)
                    parent = stage_node(run_id, artifact_stage, run_evidence)
                    text = None
                    if artifact_reader is not None and _entity(kind) in {
                            ArtifactEntityKind.RTL, ArtifactEntityKind.CONFIG,
                            ArtifactEntityKind.LOG, ArtifactEntityKind.REPORT}:
                        try:
                            excerpt = artifact_reader(
                                run_id, artifact_id, offset=0,
                                max_bytes=max_excerpt_bytes)
                            text = str(excerpt["text"])
                            content_by_artifact[(run_id, artifact_id)] = text
                            if int(artifact.get("size_bytes") or 0) > max_excerpt_bytes:
                                unknowns.append(
                                    f"Artifact {artifact_id} line index is truncated to its first {max_excerpt_bytes} bytes.")
                        except Exception:
                            unknowns.append(
                                f"Artifact {artifact_id} could not be read through the bounded Runtime port.")
                    line_end = max(1, len(text.splitlines())) if text is not None else None
                    node = ArtifactIndexNode(
                        _id("node", (run_id, "artifact", artifact_id)), _entity(kind),
                        run_id, artifact_stage, f"{kind} artifact {document}",
                        (evidence,), artifact_id=artifact_id, artifact_kind=kind,
                        document_name=document,
                        line_start=1 if text is not None else None,
                        line_end=line_end,
                        location_precision="whole_excerpt" if text is not None else None,
                    )
                    node.validate(); nodes.append(node)
                    artifact_nodes[(run_id, artifact_id)] = node
                    attempt_artifacts.append(node)
                    hashes.setdefault(evidence.sha256, []).append(node)
                    edge = ArtifactIndexEdge(
                        _id("edge", (parent.node_id, node.node_id, "stage")),
                        ArtifactRelation.STAGE_PRODUCED, parent.node_id,
                        node.node_id, (evidence, run_evidence),
                    )
                    edge.validate(); edges.append(edge)
                if attempt_artifacts:
                    anchor = attempt_artifacts[0]
                    for other in attempt_artifacts[1:]:
                        edge = ArtifactIndexEdge(
                            _id("edge", (anchor.node_id, other.node_id, "attempt")),
                            ArtifactRelation.CO_REGISTERED, anchor.node_id,
                            other.node_id,
                            tuple(dict.fromkeys((*anchor.evidence, *other.evidence))),
                        )
                        edge.validate(); edges.append(edge)
                metric_rows = list(attempt.get("metrics", ()))
                for artifact in attempt.get("artifacts", ()):
                    metadata = artifact.get("metadata")
                    if (isinstance(metadata, Mapping)
                            and metadata.get("runtime_authority") == "protected_evaluator"
                            and isinstance(metadata.get("canonical_metrics"), Mapping)):
                        metric_rows.extend({
                            "name": name, "value": value, "unit": None,
                            "source_artifact_id": artifact.get("artifact_id"),
                            "authority": "protected_evaluator",
                        } for name, value in metadata["canonical_metrics"].items())
                for row_index, metric in enumerate(metric_rows):
                    name, value = metric.get("name"), metric.get("value")
                    source_id = metric.get("source_artifact_id")
                    source = artifact_nodes.get((run_id, source_id))
                    if (not isinstance(name, str) or not name or isinstance(value, bool)
                            or not isinstance(value, (int, float)) or source is None):
                        if isinstance(name, str) and name:
                            unknowns.append(
                                f"Metric {name} has no registered source artifact and was not indexed.")
                        continue
                    text = content_by_artifact.get((run_id, source_id))
                    line = _line_for(text, name)
                    metric_node = ArtifactIndexNode(
                        _id("node", (run_id, attempt.get("attempt_id"), "metric",
                                     row_index, name, value, source_id)),
                        ArtifactEntityKind.METRIC, run_id, source.stage,
                        f"metric {name}={value}", source.evidence,
                        artifact_id=source_id, artifact_kind=source.artifact_kind,
                        metric_name=name, metric_value=float(value),
                        metric_unit=str(metric.get("unit") or "unknown"),
                        document_name=source.document_name if line is not None else None,
                        line_start=line, line_end=line,
                        location_precision="exact_line" if line is not None else None,
                    )
                    metric_node.validate(); nodes.append(metric_node)
                    edge = ArtifactIndexEdge(
                        _id("edge", (metric_node.node_id, source.node_id, "metric")),
                        ArtifactRelation.METRIC_DERIVED_FROM, metric_node.node_id,
                        source.node_id, source.evidence,
                    )
                    edge.validate(); edges.append(edge)

    for sha256, same_content in hashes.items():
        if len({item.run_id for item in same_content}) < 2:
            continue
        anchor = same_content[0]
        for other in same_content[1:]:
            if other.run_id == anchor.run_id:
                continue
            edge = ArtifactIndexEdge(
                _id("edge", (anchor.node_id, other.node_id, "content", sha256)),
                ArtifactRelation.CONTENT_MATCH, anchor.node_id, other.node_id,
                tuple(dict.fromkeys((*anchor.evidence, *other.evidence))),
            )
            edge.validate(); edges.append(edge)

    evidence = tuple(dict.fromkeys(pointer for node in nodes
                                   for pointer in node.evidence))
    index = CrossArtifactIndex(
        _id("artifact-index", (scope_id, run_ids,
                               [item.node_id for item in nodes])),
        scope_id, tuple(run_ids), tuple(nodes), tuple(edges),
        tuple(dict.fromkeys(unknowns)), evidence,
    )
    index.validate()
    return index
