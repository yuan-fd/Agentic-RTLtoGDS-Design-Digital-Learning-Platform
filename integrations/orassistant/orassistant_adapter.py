#!/usr/bin/env python3
"""Bounded ORAssistant native-retrieval adapter.

The platform owns source/corpus admission and evidence normalization.  The
retrieval and formatting calls below are the pinned upstream implementations;
this process deliberately has no OpenROAD, MCP, database, or network surface.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.machinery
import json
import os
import shutil
import subprocess
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


PLUGIN_ID = "orassistant"
UPSTREAM_COMMIT = "a5df2dfe54869fd929d966a4ce335b9d0892f676"
UPSTREAM_TREE = "9981a08b1166c82b32cd086d343dbe4a1347f84f"
UPSTREAM_LICENSE_SHA256 = "81ea2669e3bfcdbf8c31ee10e5c41f0401109814793a7487a6a5901301ef71ae"
UPSTREAM_FILES = {
    "backend/src/chains/bm25_retriever_chain.py":
        "e2602a9547f435f446d51c0ffacf29937086e2ebccd61c3a266803d16f5f3f66",
    "backend/src/chains/similarity_retriever_chain.py":
        "f42a5d5aafd45097b6302e49b837d64a78962e4d2d896071038e411acaf2679f",
    "backend/src/vectorstores/faiss.py":
        "15a739888ede2921b60e64b0239042838b4083785b5b8b5651bbf45189d75dbc",
    "backend/src/tools/format_docs.py":
        "b8376e2082a87d9d383e78571f91ecd83149008d0191622b8a0e186fef36fb42",
    "backend/src/tools/process_md.py":
        "97ef2bf0238c62813a555fb087c80b2a26a5c31499348aa874659157b719911f",
}
CORPUS_COMMIT = "63ed2e0fe5992099b7d528177bbb7a4df9523907"
CORPUS_TREE = "e32e44b5594f05dbb57f37cd81c032998ad1aa2c"
CORPUS_LICENSE_SHA256 = "28cfc93cb2b552192bc316259d2c2a1aa5a980018cda1c5cd9b1143c9151aebb"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode()).hexdigest()


def _write(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _git_identity(root: Path, *, commit: str, tree: str) -> dict[str, str]:
    if not root.is_dir():
        raise FileNotFoundError(f"admitted checkout is missing: {root}")
    git = ("git", "-C", str(root))
    actual_commit = subprocess.check_output((*git, "rev-parse", "HEAD"), text=True).strip()
    actual_tree = subprocess.check_output((*git, "rev-parse", "HEAD^{tree}"), text=True).strip()
    if actual_commit != commit or actual_tree != tree:
        raise ValueError("admitted checkout commit/tree drift")
    if subprocess.run(
        (*git, "symbolic-ref", "-q", "HEAD"), stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, check=False,
    ).returncode == 0:
        raise ValueError("admitted checkout must be detached")
    if subprocess.check_output(
        (*git, "status", "--porcelain", "--untracked-files=all"), text=True,
    ):
        raise ValueError("admitted checkout must be clean")
    return {"commit": actual_commit, "tree": actual_tree}


def _source() -> tuple[Path, dict[str, Any]]:
    root = Path(os.environ["ORASSISTANT_SOURCE"]).expanduser().resolve()
    identity = _git_identity(root, commit=UPSTREAM_COMMIT, tree=UPSTREAM_TREE)
    if _sha256(root / "LICENSE") != UPSTREAM_LICENSE_SHA256:
        raise ValueError("ORAssistant license drift")
    for relative, expected in UPSTREAM_FILES.items():
        if _sha256(root / relative) != expected:
            raise ValueError(f"ORAssistant retrieval source drift: {relative}")
    return root, {
        "repository": "https://github.com/The-OpenROAD-Project/ORAssistant.git",
        **identity,
        "license": "GPL-3.0-only",
        "license_sha256": UPSTREAM_LICENSE_SHA256,
        "retrieval_files": dict(UPSTREAM_FILES),
    }


def _corpus() -> tuple[Path, dict[str, Any], Mapping[str, Any]]:
    source = Path(os.environ["ORASSISTANT_CORPUS_SOURCE"]).expanduser().resolve()
    identity = _git_identity(source, commit=CORPUS_COMMIT, tree=CORPUS_TREE)
    if _sha256(source / "LICENSE") != CORPUS_LICENSE_SHA256:
        raise ValueError("OpenROAD corpus license drift")
    lock = Path(os.environ["ORASSISTANT_CORPUS_LOCK"]).expanduser().resolve()
    expected = os.environ["ORASSISTANT_CORPUS_LOCK_SHA256"]
    if _sha256(lock) != expected:
        raise ValueError("OpenROAD corpus lock drift")
    value = json.loads(lock.read_text(encoding="utf-8"))
    if value.get("schema_version") != 1 or value.get("corpus_id") != "openroad-source-docs-63ed2e0":
        raise ValueError("unsupported OpenROAD corpus lock")
    locked_source = value.get("source") or {}
    if locked_source.get("commit") != identity["commit"] or locked_source.get("tree") != identity["tree"]:
        raise ValueError("corpus lock does not identify the admitted OpenROAD checkout")
    return source, {
        "repository": "https://github.com/The-OpenROAD-Project/OpenROAD.git",
        **identity,
        "license": "BSD-3-Clause",
        "license_sha256": CORPUS_LICENSE_SHA256,
        "lock_sha256": expected,
    }, value


def _selected_documents(root: Path, lock: Mapping[str, Any]) -> list[Path]:
    selection = lock.get("selection")
    if not isinstance(selection, Mapping):
        raise ValueError("corpus selection is missing")
    patterns = selection.get("include")
    extensions = set(selection.get("extensions") or ())
    if not isinstance(patterns, list) or not patterns or extensions != {".md", ".txt", ".ok"}:
        raise ValueError("corpus selection is malformed")
    selected: dict[str, Path] = {}
    for pattern in patterns:
        if not isinstance(pattern, str) or pattern.startswith(("/", "..")):
            raise ValueError("unsafe corpus glob")
        for candidate in root.glob(pattern):
            resolved = candidate.resolve()
            try:
                relative = resolved.relative_to(root)
            except ValueError as exc:
                raise ValueError("corpus document escapes its source root") from exc
            if candidate.is_symlink() or not candidate.is_file() or candidate.suffix not in extensions:
                continue
            selected[relative.as_posix()] = resolved
    paths = [selected[name] for name in sorted(selected)]
    maximum = int(selection.get("max_files", 0))
    max_bytes = int(selection.get("max_total_bytes", 0))
    if not paths or len(paths) > maximum:
        raise ValueError("corpus file count is empty or exceeds its lock")
    if sum(path.stat().st_size for path in paths) > max_bytes:
        raise ValueError("corpus byte size exceeds its lock")
    return paths


def _stage_corpus(workspace: Path, root: Path, lock: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
    stage = workspace / "data" / "corpus"
    stage.mkdir(parents=True, exist_ok=False)
    source_list: dict[str, str] = {}
    staged_to_source: dict[str, dict[str, Any]] = {}
    rows = []
    template = str(lock["citation_url_template"])
    for index, source in enumerate(_selected_documents(root, lock), 1):
        relative = source.relative_to(root).as_posix()
        source_hash = _sha256(source)
        target_name = f"{index:04d}-{hashlib.sha256(relative.encode()).hexdigest()[:16]}.md"
        target = stage / target_name
        text = source.read_text(encoding="utf-8", errors="replace")
        target.write_text(
            f"# OpenROAD source: {relative}\n\n{text}\n", encoding="utf-8",
        )
        staged_key = f"data/corpus/{target_name}"
        url = template.format(path=relative)
        source_list[staged_key] = url
        staged_to_source[staged_key] = {
            "source_path": relative, "source_url": url,
            "document_sha256": source_hash,
        }
        rows.append({"source_path": relative, "sha256": source_hash,
                     "size_bytes": source.stat().st_size, "url": url})
    source_list_path = workspace / "data" / "source_list.json"
    _write(source_list_path, source_list)
    corpus_manifest = {
        "schema_version": 1,
        "corpus_id": lock["corpus_id"],
        "documents": rows,
        "document_count": len(rows),
        "total_source_bytes": sum(row["size_bytes"] for row in rows),
    }
    corpus_manifest["corpus_sha256"] = _digest_json(corpus_manifest)
    return stage, {"manifest": corpus_manifest, "lookup": staged_to_source}


def _install_runtime_denials() -> None:
    denied_events = {
        "socket.connect", "socket.getaddrinfo", "subprocess.Popen", "os.system",
        "os.exec", "os.posix_spawn", "urllib.Request",
    }

    def deny(event: str, _args: tuple[Any, ...]) -> None:
        if event in denied_events:
            raise PermissionError(f"ORAssistant read-only runtime denied audit event: {event}")

    sys.addaudithook(deny)


def _install_denied_optional_provider_shims() -> list[str]:
    """Satisfy upstream type imports without installing denied providers.

    The selected BM25 path never instantiates embeddings or an LLM, but the
    pinned modules import their classes at module load time.  These fail-closed
    sentinels keep that optional dependency surface absent and raise if an
    upstream change ever attempts to use it.
    """
    definitions = {
        "langchain_google_vertexai": ("ChatVertexAI", "VertexAIEmbeddings"),
        "langchain_google_genai": ("ChatGoogleGenerativeAI", "GoogleGenerativeAIEmbeddings"),
        "langchain_ollama": ("ChatOllama",),
        "langchain_huggingface": ("HuggingFaceEmbeddings",),
    }

    class DeniedOptionalProvider:
        def __init__(self, *_args: Any, **_kwargs: Any):
            raise PermissionError("optional cloud/model provider is denied in ORAssistant BM25 mode")

    installed = []
    for module_name, names in definitions.items():
        module = types.ModuleType(module_name)
        module.__spec__ = importlib.machinery.ModuleSpec(module_name, loader=None)
        for name in names:
            setattr(module, name, DeniedOptionalProvider)
        sys.modules[module_name] = module
        installed.append(module_name)
    return installed


def _retrieve(source: Path, workspace: Path, stage: Path, lookup: Mapping[str, Any],
              *, query: str, top_k: int, chunk_size: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    backend = source / "backend"
    sys.path.insert(0, str(backend))
    old_cwd = Path.cwd()
    os.chdir(workspace)
    try:
        optional_provider_shims = _install_denied_optional_provider_shims()
        _install_runtime_denials()
        from src.chains.bm25_retriever_chain import BM25RetrieverChain
        from src.tools.format_docs import format_docs
        from src.tools.process_md import process_md

        documents = process_md(
            f"./{stage.relative_to(workspace).as_posix()}", split_text=True,
            chunk_size=chunk_size,
        )
        chain = BM25RetrieverChain()
        chain.create_bm25_retriever(embedded_docs=documents, search_k=top_k)
        if chain.retriever is None:
            raise RuntimeError("upstream BM25 retriever was not initialized")
        retrieved = chain.retriever.invoke(query)
        formatted_context, formatted_sources, formatted_urls, _ = format_docs(retrieved)
    finally:
        os.chdir(old_cwd)
    results = []
    for rank, document in enumerate(retrieved, 1):
        staged_key = str(document.metadata.get("source", ""))
        original = lookup.get(staged_key)
        if not isinstance(original, Mapping):
            raise ValueError("upstream retrieval returned an unregistered corpus source")
        chunk = str(document.page_content)
        results.append({
            "citation_id": f"ORAK-{rank:03d}", "rank": rank, "score": None,
            "source_path": original["source_path"],
            "source_url": original["source_url"],
            "document_sha256": original["document_sha256"],
            "chunk_sha256": hashlib.sha256(chunk.encode()).hexdigest(),
            "start_index": document.metadata.get("start_index"),
            "text": chunk,
        })
    native = {
        "entrypoint": "backend/src/chains/bm25_retriever_chain.py:BM25RetrieverChain",
        "preprocessor": "backend/src/tools/process_md.py:process_md",
        "formatter": "backend/src/tools/format_docs.py:format_docs",
        "retriever_class": type(chain.retriever).__name__,
        "processed_chunk_count": len(documents),
        "formatted_context_sha256": hashlib.sha256(formatted_context.encode()).hexdigest(),
        "formatted_source_count": len(formatted_sources),
        "formatted_url_count": len(formatted_urls),
        "denied_optional_provider_shims": optional_provider_shims,
    }
    return results, native


def _explanation(query: str, results: list[Mapping[str, Any]]) -> dict[str, Any]:
    facts = []
    for row in results[:3]:
        text = " ".join(str(row["text"]).split())
        facts.append({
            "citation_id": row["citation_id"],
            "quote": text[:600],
            "source_path": row["source_path"],
        })
    return {
        "schema_version": 1,
        "kind": "cited_error_explanation",
        "query": query,
        "status": "retrieved_evidence" if facts else "no_evidence",
        "facts": facts,
        "hypotheses": [],
        "counter_evidence": [],
        "unknowns": [
            "Retrieval alone does not prove the root cause in the user's run.",
            "Confirm applicability against the run's exact stage, log context, tool version and artifacts.",
        ],
        "diagnostic_claim": False,
    }


def _task(request: Mapping[str, Any]) -> tuple[str, str, int]:
    if request.get("schema_version") != 1 or (request.get("plugin") or {}).get("plugin_id") != PLUGIN_ID:
        raise ValueError("invalid ORAssistant adapter envelope")
    task = request.get("task")
    if not isinstance(task, Mapping) or task.get("plugin_id") != PLUGIN_ID:
        raise ValueError("task does not target ORAssistant")
    inputs, parameters = task.get("inputs"), task.get("parameters")
    if not isinstance(inputs, Mapping) or set(inputs) != {"query", "purpose", "corpus_id"}:
        raise ValueError("ORAssistant inputs must be exactly query/purpose/corpus_id")
    if not isinstance(parameters, Mapping) or set(parameters) != {"retriever", "top_k"}:
        raise ValueError("ORAssistant parameters must be exactly retriever/top_k")
    query, purpose = inputs["query"], inputs["purpose"]
    if not isinstance(query, str) or not query.strip() or len(query.encode()) > 16_384 or "\x00" in query:
        raise ValueError("query must be non-empty bounded UTF-8 text")
    if purpose not in {"knowledge", "error_explanation"}:
        raise ValueError("unsupported ORAssistant purpose")
    if inputs["corpus_id"] != "openroad-source-docs-63ed2e0":
        raise ValueError("unsupported ORAssistant corpus")
    if parameters["retriever"] != "upstream-bm25":
        raise ValueError("only the admitted upstream BM25 mode is available")
    top_k = parameters["top_k"]
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 10:
        raise ValueError("top_k must be an integer between 1 and 10")
    return query.strip(), purpose, top_k


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    started = _now()
    workspace = args.result.resolve().parent
    try:
        if sys.version_info < (3, 13):
            raise RuntimeError("pinned ORAssistant revision requires Python >=3.13")
        query, purpose, top_k = _task(json.loads(args.request.read_text(encoding="utf-8")))
        source, source_identity = _source()
        corpus_root, corpus_identity, corpus_lock = _corpus()
        if corpus_lock["corpus_id"] != "openroad-source-docs-63ed2e0":
            raise ValueError("task corpus and admitted corpus differ")
        stage, staged = _stage_corpus(workspace, corpus_root, corpus_lock)
        results, native = _retrieve(
            source, workspace, stage, staged["lookup"], query=query, top_k=top_k,
            chunk_size=int(corpus_lock["selection"]["chunk_size"]),
        )
        if not results:
            raise RuntimeError("native ORAssistant retrieval returned no evidence")
        retrieval = {
            "schema_version": 1, "kind": "orassistant_native_retrieval",
            "query": query, "purpose": purpose, "method": "upstream-bm25",
            "results": results, "native": native,
        }
        explanation = _explanation(query, results)
        provenance = {
            "schema_version": 1, "plugin_id": PLUGIN_ID,
            "upstream": source_identity, "corpus_source": corpus_identity,
            "corpus_sha256": staged["manifest"]["corpus_sha256"],
            "runtime_policy": {
                "network": "denied-by-python-audit-hook-and-offline-environment",
                "mcp": "not imported", "database": "not imported",
                "serialized_vectorstore": "not loaded", "eda_execution": "not available",
            },
            "claim_scope": "read-only retrieval integration; no broad answer-accuracy or diagnosis claim",
        }
        _write(workspace / "retrieval.json", retrieval)
        _write(workspace / "explanation.json", explanation)
        _write(workspace / "corpus_manifest.json", staged["manifest"])
        _write(workspace / "native_trace.json", provenance)
        artifacts = [
            {"kind": "knowledge_retrieval", "path": "retrieval.json"},
            {"kind": "knowledge_explanation", "path": "explanation.json"},
            {"kind": "knowledge_corpus_manifest", "path": "corpus_manifest.json"},
            {"kind": "knowledge_provenance", "path": "native_trace.json"},
        ]
        _write(args.result, {
            "schema_version": 1, "status": "succeeded", "exit_code": 0,
            "started_at": started, "ended_at": _now(), "metrics": [],
            "artifacts": artifacts, "failure": None,
            "provenance": {"upstream_commit": UPSTREAM_COMMIT,
                           "native_retriever": "BM25RetrieverChain"},
        })
        print(json.dumps({"event": "orassistant.retrieval.completed",
                          "result_count": len(results), "purpose": purpose}))
        return 0
    except Exception as exc:
        failure = {"category": "orassistant_retrieval_error",
                   "message": f"{type(exc).__name__}: {exc}"}
        _write(args.result, {
            "schema_version": 1, "status": "failed", "exit_code": 1,
            "started_at": started, "ended_at": _now(), "metrics": [],
            "artifacts": [], "failure": failure,
            "provenance": {"upstream_commit": UPSTREAM_COMMIT},
        })
        print(json.dumps({"event": "orassistant.retrieval.failed", **failure}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
