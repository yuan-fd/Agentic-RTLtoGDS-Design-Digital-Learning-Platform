#!/usr/bin/env python3
"""Build one real cross-run RTL-to-GDS artifact graph via Runtime reads."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
for source_root in (ROOT, *(ROOT / "packages" / name / "src" for name in
                            ("contracts", "analysis", "scheduler", "execution"))):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from openroad_platform_analysis import build_cross_artifact_index  # noqa: E402
from openroad_platform_execution import PluginRegistry  # noqa: E402
from openroad_platform_scheduler import RuntimeStore, WorkflowRuntime  # noqa: E402


SOURCE_ROOT = ROOT / "var/evidence/rtlscout-native-spec-to-gds-20260905-r8"
SOURCE = SOURCE_ROOT / "summary.json"
SOURCE_SHA256 = "602a13dc56145ab3b3e3f7c290b92c269fe4f137b54e6e14b3185f8b075f4cb0"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("refusing to overwrite artifact-graph evidence")
    if _sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError("unified Spec-to-GDS evidence drift")
    output.mkdir(parents=True, exist_ok=True)
    source = json.loads(SOURCE.read_text())
    database = SOURCE_ROOT / "state/runtime.sqlite"
    database_before = _sha256(database)
    runtime = WorkflowRuntime(
        RuntimeStore(database), PluginRegistry(),
        workspace_root=SOURCE_ROOT / "work",
    )
    views = tuple(source["runtime_views"].values())
    index = build_cross_artifact_index(
        views, scope_id="rtlscout-native-spec-to-gds-r8",
        artifact_reader=runtime.read_artifact_excerpt,
    )
    database_after = _sha256(database)
    kinds = {node.entity_kind.value for node in index.nodes}
    relations = {edge.relation.value for edge in index.edges}
    exact_lines = [node for node in index.nodes
                   if node.location_precision == "exact_line"]
    checks = {
        "source_pinned": _sha256(SOURCE) == SOURCE_SHA256,
        "all_runtime_runs_indexed": set(index.run_ids) == {
            value["run"]["run_id"] for value in views},
        "required_entities": {"rtl", "config", "log", "report", "metric", "stage"} <= kinds,
        "stage_artifact_edges": "stage_produced" in relations,
        "metric_source_edges": "metric_derived_from" in relations,
        "cross_run_content_edges": "content_match" in relations,
        "file_line_locations": bool(exact_lines) and all(
            node.line_start == node.line_end and node.document_name
            for node in exact_lines),
        "no_absolute_document_names": all(
            "/" not in node.document_name and "\\" not in node.document_name
            for node in index.nodes if node.document_name),
        "registered_hash_evidence": all(
            pointer.ref.startswith(("artifact:runtime-", "run:"))
            for pointer in index.evidence),
        "runtime_database_unchanged": database_before == database_after,
        "raw_workspace_hidden": "/share/home/" not in json.dumps(index.to_dict()),
    }
    summary = {
        "schema_version": 1, "kind": "edatracer-style-artifact-graph-acceptance",
        "accepted": all(checks.values()),
        "reference": {
            "paper": "EDATracer arXiv:2608.04032v1",
            "adapted_concept": "typed knowledge graph with evidence-grounded cross-artifact retrieval",
            "vector_index_implemented": False,
            "code_reuse": False,
        },
        "input_evidence": {"source_document": str(SOURCE.relative_to(ROOT)),
                           "sha256": SOURCE_SHA256},
        "counts": {"runs": len(index.run_ids), "nodes": len(index.nodes),
                   "edges": len(index.edges), "exact_line_nodes": len(exact_lines),
                   "unknowns": len(index.unknowns)},
        "index": index.to_dict(), "checks": checks,
        "claim_boundary": (
            "A bounded typed graph over the five real Runtime runs in one accepted "
            "Spec-to-GDS flow, with Runtime-mediated excerpts and artifact/file-line "
            "citations. It is not EDATracer's vector index, dataset scale, or benchmark result."
        ),
    }
    path = output / "summary.json"
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    digest = _sha256(path)
    (output / "summary.sha256").write_text(f"{digest}  summary.json\n")
    print(json.dumps({"accepted": summary["accepted"], "counts": summary["counts"],
                      "summary": str(path), "sha256": digest}, indent=2))
    return 0 if summary["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
