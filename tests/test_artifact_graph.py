from __future__ import annotations

from openroad_platform_analysis import build_cross_artifact_index
from openroad_platform_contracts import (
    ArtifactEntityKind, ArtifactRelation, CrossArtifactIndex,
)


def _view(run_id, artifact_id, sha, *, with_metric=True):
    metrics = ([{
        "name": "finish__timing__setup__ws", "value": -0.1, "unit": "ns",
        "source_artifact_id": artifact_id,
    }] if with_metric else [])
    metrics.append({"name": "orphan_metric", "value": 1,
                    "source_artifact_id": None})
    return {
        "run": {"run_id": run_id, "status": "succeeded", "task_id": f"task-{run_id}"},
        "events": [{"event_type": "tool.stage.started",
                    "payload": {"tool_stage": "finish"}}],
        "stages": [{"stage_key": "rtl_to_gds", "attempts": [{
            "attempt_id": f"attempt-{run_id}", "status": "succeeded",
            "artifacts": [
                {"artifact_id": artifact_id, "kind": "report",
                 "store_key": "logs/nangate/design/base/6_report.json",
                 "size_bytes": 80, "sha256": sha, "metadata": {}},
                {"artifact_id": f"rtl-{run_id}", "kind": "rtl",
                 "store_key": "input/top.v", "size_bytes": 30,
                 "sha256": "b" * 64, "metadata": {}},
                {"artifact_id": f"config-{run_id}", "kind": "config",
                 "store_key": "design/config.mk", "size_bytes": 20,
                 "sha256": ("c" if run_id == "run-1" else "d") * 64,
                 "metadata": {}},
                {"artifact_id": f"log-{run_id}", "kind": "log",
                 "store_key": "logs/flow.log", "size_bytes": 20,
                 "sha256": ("e" if run_id == "run-1" else "f") * 64,
                 "metadata": {}},
            ], "metrics": metrics,
        }]}],
    }


def test_graph_indexes_cross_run_artifacts_metrics_stages_and_lines():
    views = (_view("run-1", "report-1", "a" * 64),
             _view("run-2", "report-2", "a" * 64))
    texts = {
        "report-1": '{\n "finish__timing__setup__ws": -0.1\n}\n',
        "report-2": '{\n "finish__timing__setup__ws": -0.1\n}\n',
        "rtl-run-1": "module top; endmodule\n", "rtl-run-2": "module top; endmodule\n",
        "config-run-1": "CORE_UTILIZATION=20\n", "config-run-2": "CORE_UTILIZATION=20\n",
        "log-run-1": "flow completed\n", "log-run-2": "flow completed\n",
    }

    def reader(_run_id, artifact_id, **_bounds):
        return {"text": texts[artifact_id]}

    index = build_cross_artifact_index(
        views, scope_id="spec-to-gds-1", artifact_reader=reader)
    assert CrossArtifactIndex.from_dict(index.to_dict()) == index
    kinds = {node.entity_kind for node in index.nodes}
    assert {ArtifactEntityKind.RTL, ArtifactEntityKind.CONFIG,
            ArtifactEntityKind.LOG, ArtifactEntityKind.REPORT,
            ArtifactEntityKind.METRIC, ArtifactEntityKind.STAGE} <= kinds
    metrics = [node for node in index.nodes
               if node.entity_kind is ArtifactEntityKind.METRIC]
    assert len(metrics) == 2
    assert all(node.document_name == "6_report.json" and node.line_start == 2
               and node.location_precision == "exact_line" for node in metrics)
    relations = {edge.relation for edge in index.edges}
    assert ArtifactRelation.STAGE_PRODUCED in relations
    assert ArtifactRelation.METRIC_DERIVED_FROM in relations
    assert ArtifactRelation.CO_REGISTERED in relations
    assert ArtifactRelation.CONTENT_MATCH in relations
    assert any("orphan_metric" in item for item in index.unknowns)


def test_graph_does_not_expose_workspace_paths_or_invent_unread_lines():
    view = _view("run-1", "report-1", "a" * 64)
    view["stages"][0]["attempts"][0]["workspace"] = "/private/runtime/work"
    index = build_cross_artifact_index((view,), scope_id="bounded-index")
    encoded = str(index.to_dict())
    assert "/private/runtime/work" not in encoded
    artifacts = [node for node in index.nodes if node.artifact_id]
    assert all(node.line_start is None for node in artifacts)
    assert all("/" not in node.document_name for node in artifacts if node.document_name)
