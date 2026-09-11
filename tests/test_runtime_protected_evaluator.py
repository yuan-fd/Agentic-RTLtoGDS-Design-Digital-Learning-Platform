from __future__ import annotations

import hashlib
import platform
import sys
from pathlib import Path

from openroad_platform_contracts.platform import PluginManifest, RuntimeStatus, TaskSpec
from openroad_platform_execution.registry import PluginRegistry
from openroad_platform_scheduler.runtime import WorkflowRuntime
from openroad_platform_scheduler.runtime_store import RuntimeStore


FIXTURES = Path(__file__).parent / "fixtures"


class _Evaluator:
    def evaluate(self, *, manifest, task, workspace):
        assert manifest.plugin_id == "echo" and task.task_id == "protected-evaluator"
        target = Path(workspace) / "protected.json"
        target.write_text('{"canonical":true}\n', encoding="utf-8")
        return ({"kind": "report", "path": "protected.json", "metadata": {"producer": "test"}},)


def test_runtime_registers_validated_post_execution_evaluator_artifact(tmp_path):
    manifest = PluginManifest(
        plugin_id="echo", plugin_version="1.0.0",
        adapter_entry=(sys.executable, str(FIXTURES / "echo_adapter.py")),
        capabilities=("test.echo",), supported_arch=(platform.machine(),),
        input_schema={"type": "object"}, output_schema={"type": "object"},
        artifact_rules=({"kind": "report", "required": True},),
    )
    runtime = WorkflowRuntime(
        RuntimeStore(tmp_path / "runtime.db"), PluginRegistry([manifest]),
        workspace_root=tmp_path / "workspaces", protected_evaluator=_Evaluator(),
    )
    run = runtime.submit(TaskSpec(
        task_id="protected-evaluator", project_id="project", design_id="design",
        plugin_id="echo", inputs={}, expected_artifacts=("report",), timeout_seconds=30,
    ))
    assert runtime.execute_once(run.run_id).status is RuntimeStatus.SUCCEEDED
    attempt = runtime.describe(run.run_id)["stages"][0]["attempts"][0]
    artifact = next(item for item in attempt["artifacts"] if item["store_key"] == "protected.json")
    assert artifact["metadata"]["producer"] == "test"
    assert artifact["sha256"] == hashlib.sha256(
        (Path(attempt["workspace"]) / "protected.json").read_bytes()).hexdigest()


def test_runtime_rejects_evaluator_artifact_outside_attempt_workspace(tmp_path):
    class _UnsafeEvaluator:
        def evaluate(self, **_kwargs):
            return ({"kind": "report", "path": "../escape.json"},)

    manifest = PluginManifest(
        plugin_id="echo", plugin_version="1.0.0",
        adapter_entry=(sys.executable, str(FIXTURES / "echo_adapter.py")),
        capabilities=("test.echo",), supported_arch=(platform.machine(),),
        input_schema={"type": "object"}, output_schema={"type": "object"},
        artifact_rules=({"kind": "report", "required": True},),
    )
    runtime = WorkflowRuntime(
        RuntimeStore(tmp_path / "runtime.db"), PluginRegistry([manifest]),
        workspace_root=tmp_path / "workspaces", protected_evaluator=_UnsafeEvaluator(),
    )
    run = runtime.submit(TaskSpec(
        task_id="protected-evaluator-escape", project_id="project", design_id="design",
        plugin_id="echo", inputs={}, expected_artifacts=("report",), timeout_seconds=30,
    ))
    assert runtime.execute_once(run.run_id).status is RuntimeStatus.FAILED
    attempt = runtime.describe(run.run_id)["stages"][0]["attempts"][0]
    assert attempt["failure"]["category"] == "runtime_error"
    assert all(item["store_key"] != "../escape.json" for item in attempt["artifacts"])


def test_runtime_rejects_adapter_spoofing_protected_evaluator_metadata(tmp_path):
    class _SpoofingAdapter:
        def execute(self, manifest, task, *, workspace, **_kwargs):
            from types import SimpleNamespace
            path = Path(workspace) / "spoof.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{"canonical":false}\n', encoding="utf-8")
            result = SimpleNamespace(status=RuntimeStatus.SUCCEEDED, exit_code=0,
                                     metrics=(), failure=None)
            return SimpleNamespace(result=result, artifacts=({
                "kind": "report", "store_key": "spoof.json",
                "size_bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "metadata": {"producer": "protected-orfs-evaluator",
                             "official_qor": True},
            },))

        def validate_additional_artifacts(self, workspace, manifest, artifacts):
            return tuple(artifacts)

    manifest = PluginManifest(
        plugin_id="echo", plugin_version="1.0.0",
        adapter_entry=(sys.executable, str(FIXTURES / "echo_adapter.py")),
        capabilities=("test.echo",), supported_arch=(platform.machine(),),
        input_schema={"type": "object"}, output_schema={"type": "object"},
        artifact_rules=({"kind": "report", "required": True},),
    )
    runtime = WorkflowRuntime(
        RuntimeStore(tmp_path / "runtime.db"), PluginRegistry([manifest]),
        workspace_root=tmp_path / "workspaces", adapter=_SpoofingAdapter(),
    )
    run = runtime.submit(TaskSpec(
        task_id="spoof", project_id="project", design_id="design",
        plugin_id="echo", inputs={}, expected_artifacts=("report",), timeout_seconds=30,
    ))
    assert runtime.execute_once(run.run_id).status is RuntimeStatus.FAILED
    attempt = runtime.describe(run.run_id)["stages"][0]["attempts"][0]
    assert "reserved protected evaluator metadata" in attempt["failure"]["message"]
