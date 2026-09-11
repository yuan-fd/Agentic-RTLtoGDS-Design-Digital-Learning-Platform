from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from openroad_platform_contracts import KnowledgeQueryRequest
from openroad_platform_execution import (
    ORAssistantKnowledgeTaskFactory,
    ORASSISTANT_CAPABILITY,
    ORASSISTANT_CORPUS_ID,
    PluginRegistry,
    build_orassistant_task,
    orassistant_plugin_manifest,
)


REPOSITORY = Path(__file__).resolve().parents[1]


def _adapter_module():
    path = REPOSITORY / "integrations/orassistant/orassistant_adapter.py"
    spec = importlib.util.spec_from_file_location("tested_orassistant_adapter", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_task_is_a_bounded_read_only_query() -> None:
    task = build_orassistant_task(
        project_id="p", design_id="aes",
        query="What does [WARNING DRT-0349] mean?",
        purpose="error_explanation", top_k=4, task_id="orassistant-test",
    )
    assert task.inputs == {
        "query": "What does [WARNING DRT-0349] mean?",
        "purpose": "error_explanation",
        "corpus_id": ORASSISTANT_CORPUS_ID,
    }
    assert task.parameters == {"retriever": "upstream-bm25", "top_k": 4}
    assert task.max_attempts == 1
    assert "command" not in json.dumps(task.to_dict()).lower()


def test_generic_knowledge_factory_maps_only_the_typed_request() -> None:
    factory = ORAssistantKnowledgeTaskFactory()
    request = KnowledgeQueryRequest(
        project_id="p", design_id="aes", query="Explain DRT-0349",
        purpose="error_explanation", top_k=3, task_id="knowledge-call",
        labels={"l1_goal_id": "goal-1", "l1_call_id": "call-1"},
    )
    task = factory.build(request)
    factory.validate_task(task)
    assert task.plugin_id == "orassistant"
    assert task.labels["l1_goal_id"] == "goal-1"
    assert task.inputs["query"] == "Explain DRT-0349"
    with pytest.raises(ValueError, match="bounded"):
        KnowledgeQueryRequest("p", "aes", "bad\x00query").validate()


@pytest.mark.parametrize("query", ["", "x" * 16385])
def test_task_rejects_invalid_queries(query: str) -> None:
    with pytest.raises(ValueError, match="query"):
        build_orassistant_task(project_id="p", design_id="d", query=query)


def test_manifest_advertises_retrieval_only(tmp_path: Path) -> None:
    source, corpus = tmp_path / "source", tmp_path / "corpus"
    source.mkdir(); corpus.mkdir()
    manifest = orassistant_plugin_manifest(
        source_checkout=source, corpus_checkout=corpus,
        python_executable=sys.executable,
    )
    assert manifest.capabilities == (ORASSISTANT_CAPABILITY,)
    assert all("mcp" not in item and "eda" not in item for item in manifest.capabilities)
    assert manifest.environment["HF_HUB_OFFLINE"] == "1"
    assert manifest.environment["TRANSFORMERS_OFFLINE"] == "1"
    assert manifest.environment["ORASSISTANT_CORPUS_LOCK_SHA256"]


def test_static_manifest_is_discoverable_and_uses_locked_launcher() -> None:
    manifest = PluginRegistry.from_directory(
        REPOSITORY / "integrations/orassistant"
    ).resolve("orassistant", capability=ORASSISTANT_CAPABILITY)
    assert manifest.plugin_version == "a5df2dfe"
    assert manifest.adapter_entry[0] == "python3"
    assert manifest.adapter_entry[1].endswith("/integrations/orassistant/orassistant_launcher.py")


def test_manifest_preserves_virtual_environment_launcher(tmp_path: Path) -> None:
    source, corpus = tmp_path / "source", tmp_path / "corpus"
    source.mkdir(); corpus.mkdir()
    base = tmp_path / "python-base"
    base.write_text("binary")
    base.chmod(0o755)
    venv = tmp_path / "venv-python"
    venv.symlink_to(base)
    manifest = orassistant_plugin_manifest(
        source_checkout=source, corpus_checkout=corpus, python_executable=venv,
    )
    assert manifest.adapter_entry[0] == str(venv.absolute())


def test_adapter_rejects_shell_or_remote_index_fields() -> None:
    module = _adapter_module()
    request = {
        "schema_version": 1,
        "plugin": {"plugin_id": "orassistant"},
        "task": {
            "plugin_id": "orassistant",
            "inputs": {
                "query": "DRT-0349", "purpose": "error_explanation",
                "corpus_id": ORASSISTANT_CORPUS_ID,
                "command": "make finish",
            },
            "parameters": {"retriever": "upstream-bm25", "top_k": 5},
        },
    }
    with pytest.raises(ValueError, match="exactly"):
        module._task(request)
    request["task"]["inputs"].pop("command")
    request["task"]["parameters"]["faiss_pickle_url"] = "https://example.invalid/db.pkl"
    with pytest.raises(ValueError, match="exactly"):
        module._task(request)


def test_source_lock_denies_execution_and_unsafe_deserialization() -> None:
    lock = json.loads(
        (REPOSITORY / "integrations/orassistant/source.lock.json").read_text()
    )
    assert lock["source"]["commit"] == "a5df2dfe54869fd929d966a4ce335b9d0892f676"
    assert lock["execution_policy"]["deny_shell_or_eda_execution"] is True
    assert lock["execution_policy"]["deny_serialized_vectorstore_loading"] is True
    source = (REPOSITORY / "integrations/orassistant/orassistant_adapter.py").read_text()
    assert "BM25RetrieverChain" in source
    assert ".load_db(" not in source
    assert "openroad_mcp" not in source
