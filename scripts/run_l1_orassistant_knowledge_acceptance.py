#!/usr/bin/env python3
"""Accept one real L1 typed knowledge call through Policy/Runtime/ORAssistant."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
for source_root in (ROOT, *(ROOT / "packages" / name / "src" for name in
                            ("contracts", "execution", "scheduler", "analysis"))):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from apps.l1_workbench.service import WorkbenchService  # noqa: E402


QUERY = "What does [WARNING DRT-0349] mean?"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("refusing to overwrite L1 ORAssistant acceptance evidence")
    output.mkdir(parents=True, exist_ok=True)

    service = WorkbenchService(output / "state", backend="smoke")
    if service.knowledge_factory is None:
        raise RuntimeError("locked ORAssistant capability is unavailable to Workbench")
    session = service.start("Explain an OpenROAD routing warning with citations; do not run EDA.")
    session = service.answer(session.session_id, [{
        "question_id": "objective-1", "field": "objective",
        "value": "read-only cited explanation; no EDA execution",
    }])
    plan = service.query_openroad_knowledge(
        session.session_id, QUERY,
        "Retrieve bounded upstream OpenROAD evidence before explaining the warning.",
        purpose="error_explanation", top_k=5,
    )
    receipt = plan["receipt"]
    run_id = receipt["result"]["run_id"]
    view = service.runtime.describe(run_id)
    events = service.events(session.session_id)
    event_tail = [event["kind"] for event in events[-3:]]
    artifacts = [
        artifact for stage in view.get("stages", ())
        for attempt in stage.get("attempts", ())
        for artifact in attempt.get("artifacts", ())
    ]
    citation = receipt["result"]["citations"][0]
    checks = {
        "typed_tool": plan["call"]["tool"] == "query_openroad_knowledge",
        "policy_runtime_trace": event_tail == [
            "tool_called", "policy_decided", "tool_receipt"],
        "policy_allowed": events[-2].get("policy_verdict") == "allow",
        "runtime_succeeded": view["run"]["status"] == "succeeded",
        "orassistant_executed": view["run"]["task_spec"]["plugin_id"] == "orassistant",
        "knowledge_capability": receipt["result"]["capability"] ==
            "knowledge.openroad.retrieve",
        "all_artifacts_registered": {item["kind"] for item in artifacts} == {
            "knowledge_retrieval", "knowledge_explanation",
            "knowledge_corpus_manifest", "knowledge_provenance"},
        "citation_resolves_to_registered_artifact": citation["evidence"]["ref"] in {
            f"artifact:runtime-{item['artifact_id']}" for item in artifacts},
        "document_and_chunk_hashes": len(citation["document_sha256"]) == 64 and
            len(citation["chunk_sha256"]) == 64,
        "warning_evidence_retrieved": "DRT-0349" in citation["excerpt"],
        "no_diagnostic_overclaim": receipt["result"]["diagnostic_claim"] is False and
            bool(receipt["result"]["unknowns"]),
        "no_eda_budget_consumed": service._load(session.session_id)[0].remaining_budget.max_eda_runs == 3,
        "no_eda_runtime_plugin": all(
            run.task_spec.plugin_id == "orassistant"
            for run in service.runtime.store.list_runs()),
    }
    summary = {
        "schema_version": 1,
        "kind": "l1-orassistant-typed-knowledge-acceptance",
        "accepted": all(checks.values()),
        "query": QUERY,
        "session_id": session.session_id,
        "trace_id": session.trace_id,
        "run_id": run_id,
        "plan": plan,
        "runtime_view": view,
        "trace_events": events,
        "checks": checks,
        "claim_boundary": (
            "One real read-only L1 SemanticToolCall passed Policy, executed the pinned "
            "ORAssistant BM25 capability under Runtime, and returned registered-artifact "
            "citations. This is not a root-cause diagnosis or RAG-quality claim."
        ),
    }
    path = output / "summary.json"
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    digest = _sha256(path)
    (output / "summary.sha256").write_text(f"{digest}  summary.json\n")
    print(json.dumps({"accepted": summary["accepted"], "run_id": run_id,
                      "summary": str(path), "sha256": digest}, indent=2))
    return 0 if summary["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
