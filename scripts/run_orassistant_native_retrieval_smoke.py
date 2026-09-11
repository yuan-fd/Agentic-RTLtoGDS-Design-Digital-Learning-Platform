#!/usr/bin/env python3
"""Invoke the pinned ORAssistant preprocessing/BM25 APIs without platform Runtime."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from importlib import metadata
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _adapter_module():
    path = ROOT / "integrations/orassistant/orassistant_adapter.py"
    spec = importlib.util.spec_from_file_location("orassistant_native_boundary", path)
    if not spec or not spec.loader:
        raise RuntimeError("cannot load the reviewed ORAssistant native boundary")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--query", default="What does [WARNING DRT-0349] mean?")
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("refusing to overwrite native ORAssistant smoke evidence")
    output.mkdir(parents=True, exist_ok=True)
    corpus_lock = ROOT / "integrations/orassistant/openroad-corpus.lock.json"
    os.environ.update({
        "ORASSISTANT_SOURCE": str(args.source.expanduser().resolve()),
        "ORASSISTANT_CORPUS_SOURCE": str(args.corpus.expanduser().resolve()),
        "ORASSISTANT_CORPUS_LOCK": str(corpus_lock),
        "ORASSISTANT_CORPUS_LOCK_SHA256": _sha256(corpus_lock),
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "HF_DATASETS_OFFLINE": "1", "LANGCHAIN_TRACING_V2": "false",
    })
    boundary = _adapter_module()
    source, upstream = boundary._source()
    corpus, corpus_identity, lock = boundary._corpus()
    stage, staged = boundary._stage_corpus(output, corpus, lock)
    results, native = boundary._retrieve(
        source, output, stage, staged["lookup"], query=args.query, top_k=5,
        chunk_size=int(lock["selection"]["chunk_size"]),
    )
    evidence_text = "\n".join(str(row["text"]) for row in results)
    checks = {
        "python_at_least_3_13": sys.version_info >= (3, 13),
        "native_bm25_entrypoint": native["entrypoint"].endswith(":BM25RetrieverChain"),
        "native_preprocessor": native["preprocessor"].endswith(":process_md"),
        "ranked_results_returned": bool(results),
        "error_code_evidence_retrieved": "DRT-0349" in evidence_text,
        "citations_are_pinned_urls": all(upstream["commit"] in row["source_url"]
                                         or corpus_identity["commit"] in row["source_url"]
                                         for row in results),
    }
    package_names = (
        "backend", "langchain", "langchain-community", "langchain-core",
        "rank-bm25", "beautifulsoup4", "markdown",
    )
    packages = {}
    for name in package_names:
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            packages[name] = None
    summary = {
        "schema_version": 1, "kind": "orassistant-native-retrieval-smoke",
        "accepted": all(checks.values()), "query": args.query,
        "upstream": upstream, "corpus_source": corpus_identity,
        "corpus_manifest": staged["manifest"], "native": native,
        "results": results, "checks": checks,
        "environment": {"python": sys.version, "packages": packages},
        "claim_boundary": "Pinned native preprocessing and BM25 retrieval only; no Runtime, answer-quality benchmark, LLM diagnosis, or EDA execution claim.",
    }
    path = output / "native_smoke.json"
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output / "native_smoke.sha256").write_text(
        f"{_sha256(path)}  native_smoke.json\n", encoding="utf-8")
    print(json.dumps({"accepted": summary["accepted"], "evidence": str(path),
                      "sha256": _sha256(path)}, indent=2))
    return 0 if summary["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
