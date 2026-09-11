"""Typed task/manifest boundary for pinned ORAssistant read-only retrieval."""

from __future__ import annotations

import hashlib
import os
import platform
import sys
import uuid
from pathlib import Path

from openroad_platform_contracts import KnowledgeQueryRequest, PluginManifest, TaskSpec


ORASSISTANT_PLUGIN_ID = "orassistant"
ORASSISTANT_PLUGIN_VERSION = "a5df2dfe"
ORASSISTANT_CAPABILITY = "knowledge.openroad.retrieve"
ORASSISTANT_CORPUS_ID = "openroad-source-docs-63ed2e0"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_orassistant_task(
    *, project_id: str, design_id: str, query: str,
    purpose: str = "knowledge", top_k: int = 5,
    task_id: str | None = None, timeout_seconds: int = 900,
    labels: dict[str, str] | None = None,
) -> TaskSpec:
    if not isinstance(query, str) or not query.strip() or len(query.encode()) > 16_384:
        raise ValueError("query must be non-empty and at most 16384 UTF-8 bytes")
    if purpose not in {"knowledge", "error_explanation"}:
        raise ValueError("purpose must be knowledge or error_explanation")
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 10:
        raise ValueError("top_k must be an integer between 1 and 10")
    task = TaskSpec(
        task_id=task_id or f"orassistant-{uuid.uuid4().hex}",
        project_id=project_id, design_id=design_id,
        plugin_id=ORASSISTANT_PLUGIN_ID,
        inputs={"query": query.strip(), "purpose": purpose,
                "corpus_id": ORASSISTANT_CORPUS_ID},
        parameters={"retriever": "upstream-bm25", "top_k": top_k},
        timeout_seconds=timeout_seconds, max_attempts=1,
        expected_artifacts=(
            "knowledge_retrieval", "knowledge_explanation",
            "knowledge_corpus_manifest", "knowledge_provenance",
        ),
        labels={
            "capability": ORASSISTANT_CAPABILITY,
            "knowledge_owner": "upstream:ORAssistant",
            "execution_owner": "platform-runtime",
            "claim_scope": "retrieval-integration-only",
            **dict(labels or {}),
        },
    )
    task.validate()
    return task


class ORAssistantKnowledgeTaskFactory:
    """Implement the generic knowledge port with the pinned ORAssistant task."""

    capability = ORASSISTANT_CAPABILITY

    def build(self, request: KnowledgeQueryRequest) -> TaskSpec:
        if not isinstance(request, KnowledgeQueryRequest):
            raise TypeError("ORAssistant factory requires KnowledgeQueryRequest")
        request.validate()
        task = build_orassistant_task(
            project_id=request.project_id, design_id=request.design_id,
            query=request.query, purpose=request.purpose, top_k=request.top_k,
            task_id=request.task_id, labels=request.labels,
        )
        self.validate_task(task)
        return task

    @staticmethod
    def validate_task(task: TaskSpec) -> None:
        task.validate()
        if (task.plugin_id != ORASSISTANT_PLUGIN_ID
                or task.inputs.get("corpus_id") != ORASSISTANT_CORPUS_ID
                or set(task.inputs) != {"query", "purpose", "corpus_id"}
                or set(task.parameters) != {"retriever", "top_k"}
                or task.parameters.get("retriever") != "upstream-bm25"):
            raise ValueError("TaskSpec is outside the pinned ORAssistant boundary")


def orassistant_plugin_manifest(
    *, source_checkout: str | Path, corpus_checkout: str | Path,
    python_executable: str | Path = sys.executable,
    default_timeout_seconds: int = 900,
) -> PluginManifest:
    source = Path(source_checkout).expanduser().resolve()
    corpus = Path(corpus_checkout).expanduser().resolve()
    # Preserve a virtual-environment launcher symlink.  Resolving it selects
    # the base interpreter and silently drops the venv's site-packages.
    python = Path(python_executable).expanduser().absolute()
    if not source.is_dir() or not corpus.is_dir():
        raise FileNotFoundError("ORAssistant source and OpenROAD corpus checkouts are required")
    if not python.is_file() or not os.access(python, os.X_OK):
        raise FileNotFoundError("ORAssistant Python executable is unavailable")
    repository = Path(__file__).resolve().parents[4]
    adapter = repository / "integrations/orassistant/orassistant_adapter.py"
    corpus_lock = repository / "integrations/orassistant/openroad-corpus.lock.json"
    if not adapter.is_file() or not corpus_lock.is_file():
        raise FileNotFoundError("ORAssistant adapter or corpus lock is missing")
    manifest = PluginManifest(
        plugin_id=ORASSISTANT_PLUGIN_ID,
        plugin_version=ORASSISTANT_PLUGIN_VERSION,
        adapter_entry=(str(python), str(adapter)),
        capabilities=(ORASSISTANT_CAPABILITY,),
        supported_arch=(platform.machine(),),
        input_schema={
            "type": "object", "additionalProperties": False,
            "required": ["query", "purpose", "corpus_id"],
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 16384},
                "purpose": {"enum": ["knowledge", "error_explanation"]},
                "corpus_id": {"const": ORASSISTANT_CORPUS_ID},
            },
        },
        output_schema={
            "type": "object", "required": ["status", "artifacts", "provenance"],
        },
        required_tools=("git", "python3.13"),
        default_timeout_seconds=default_timeout_seconds,
        artifact_rules=tuple({"kind": kind, "required": True} for kind in (
            "knowledge_retrieval", "knowledge_explanation",
            "knowledge_corpus_manifest", "knowledge_provenance",
        )),
        environment={
            "ORASSISTANT_SOURCE": str(source),
            "ORASSISTANT_CORPUS_SOURCE": str(corpus),
            "ORASSISTANT_CORPUS_LOCK": str(corpus_lock),
            "ORASSISTANT_CORPUS_LOCK_SHA256": _sha256(corpus_lock),
            "PYTHONDONTWRITEBYTECODE": "1",
            "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
            "HF_DATASETS_OFFLINE": "1", "LANGCHAIN_TRACING_V2": "false",
            "NO_PROXY": "*", "no_proxy": "*",
            "PATH": os.pathsep.join((str(python.parent), "/usr/bin", "/bin")),
        },
    )
    manifest.validate()
    return manifest
