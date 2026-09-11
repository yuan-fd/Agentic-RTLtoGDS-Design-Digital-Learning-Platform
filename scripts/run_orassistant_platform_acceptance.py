#!/usr/bin/env python3
"""Run one cited ORAssistant error query through PluginManifest and Runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
for source_root in (ROOT, *(ROOT / "packages" / name / "src" for name in
                            ("contracts", "execution", "scheduler", "analysis"))):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from openroad_platform_execution import (  # noqa: E402
    ORASSISTANT_CAPABILITY, PluginRegistry, build_orassistant_task,
    orassistant_plugin_manifest,
)
from openroad_platform_scheduler import RuntimeStore, WorkflowRuntime  # noqa: E402


QUERY = "What does [WARNING DRT-0349] mean?"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifacts(view: dict[str, Any]) -> dict[str, tuple[dict[str, Any], Any]]:
    found = {}
    for stage in view["stages"]:
        for attempt in stage["attempts"]:
            workspace = Path(attempt["workspace"])
            for artifact in attempt["artifacts"]:
                path = (workspace / artifact["store_key"]).resolve()
                if _sha256(path) != artifact["sha256"]:
                    raise ValueError("registered ORAssistant artifact changed")
                found[artifact["kind"]] = (
                    {**artifact, "path": str(path)},
                    json.loads(path.read_text(encoding="utf-8")),
                )
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--native-evidence", type=Path, required=True)
    parser.add_argument("--static-manifest", action="store_true")
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("refusing to overwrite ORAssistant acceptance evidence")
    output.mkdir(parents=True, exist_ok=True)
    native_path = args.native_evidence.expanduser().resolve()
    native = json.loads(native_path.read_text(encoding="utf-8"))
    if not native.get("accepted") or native.get("kind") != "orassistant-native-retrieval-smoke":
        raise ValueError("a passing native smoke is required before platform admission")
    if args.static_manifest:
        expected = {
            "source": ROOT / "var/external-sources/orassistant-a5df2dfe-clean",
            "corpus": ROOT / "var/external-sources/openroad-docs-63ed2e0-clean",
            "python": ROOT / "var/external-envs/orassistant-retrieval-a5df2dfe/bin/python",
        }
        supplied = {"source": args.source.absolute(), "corpus": args.corpus.absolute(),
                    "python": args.python.absolute()}
        if supplied != {name: path.absolute() for name, path in expected.items()}:
            raise ValueError("static ORAssistant manifest is bound to repository-local locked paths")
        registry = PluginRegistry.from_directory(ROOT / "integrations/orassistant")
        manifest = registry.resolve("orassistant", capability=ORASSISTANT_CAPABILITY)
    else:
        manifest = orassistant_plugin_manifest(
            source_checkout=args.source, corpus_checkout=args.corpus,
            python_executable=args.python,
        )
        registry = PluginRegistry([manifest])
    runtime = WorkflowRuntime(
        RuntimeStore(output / "runtime.sqlite"), registry,
        workspace_root=output / "work", worker_id="orassistant-platform-acceptance",
        lease_seconds=120,
    )
    task = build_orassistant_task(
        project_id="orassistant-acceptance", design_id="openroad-knowledge",
        query=QUERY, purpose="error_explanation", top_k=5,
        task_id="orassistant-drt-0349-acceptance", timeout_seconds=900,
    )
    submitted = runtime.submit(task, capability=ORASSISTANT_CAPABILITY)
    completed = runtime.execute_once(
        submitted.run_id, on_line=lambda line: print(line, end="", flush=True)
    )
    view = runtime.describe(submitted.run_id)
    artifacts = _artifacts(view)
    retrieval = artifacts.get("knowledge_retrieval", ({}, {}))[1]
    explanation = artifacts.get("knowledge_explanation", ({}, {}))[1]
    provenance = artifacts.get("knowledge_provenance", ({}, {}))[1]
    corpus_manifest = artifacts.get("knowledge_corpus_manifest", ({}, {}))[1]
    text = "\n".join(str(row.get("text", "")) for row in retrieval.get("results", []))
    checks = {
        "runtime_succeeded": completed.status.value == "succeeded",
        "all_required_artifacts_registered": set(artifacts) == {
            "knowledge_retrieval", "knowledge_explanation",
            "knowledge_corpus_manifest", "knowledge_provenance",
        },
        "native_bm25_used": retrieval.get("method") == "upstream-bm25",
        "drt_0349_evidence_returned": "DRT-0349" in text,
        "citations_have_document_and_chunk_hashes": all(
            row.get("document_sha256") and row.get("chunk_sha256")
            for row in retrieval.get("results", [])
        ),
        "explanation_is_evidence_scoped": (
            explanation.get("diagnostic_claim") is False
            and bool(explanation.get("facts")) and bool(explanation.get("unknowns"))
        ),
        "denied_surfaces_confirmed": provenance.get("runtime_policy") == {
            "network": "denied-by-python-audit-hook-and-offline-environment",
            "mcp": "not imported", "database": "not imported",
            "serialized_vectorstore": "not loaded", "eda_execution": "not available",
        },
        "native_smoke_preceded_platform": native_path.stat().st_mtime <= Path(
            artifacts["knowledge_provenance"][0]["path"]
        ).stat().st_mtime,
    }
    summary = {
        "schema_version": 1, "kind": "orassistant-platform-acceptance",
        "accepted": all(checks.values()), "query": QUERY,
        "manifest_source": "static-capability-registry" if args.static_manifest else "programmatic",
        "run_id": submitted.run_id, "runtime_view": view,
        "artifacts": {kind: record for kind, (record, _) in artifacts.items()},
        "retrieval": retrieval, "explanation": explanation,
        "corpus_manifest": corpus_manifest, "provenance": provenance,
        "native_evidence": {"path": str(native_path), "sha256": _sha256(native_path)},
        "checks": checks,
        "claim_boundary": "One real read-only Runtime query with native ORAssistant BM25 and resolvable citations; no broad RAG-quality, LLM diagnosis, or EDA success claim.",
    }
    summary_path = output / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output / "summary.sha256").write_text(
        f"{_sha256(summary_path)}  summary.json\n", encoding="utf-8")
    print(json.dumps({"accepted": summary["accepted"], "run_id": submitted.run_id,
                      "summary": str(summary_path), "sha256": _sha256(summary_path)}, indent=2))
    return 0 if summary["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
