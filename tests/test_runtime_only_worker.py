from __future__ import annotations

import ast
import platform
import sys
import threading
import time
from pathlib import Path

import pytest

from openroad_platform_contracts import PluginManifest, RTLToGDSRequest, RunRequest, TaskSpec
from openroad_platform_execution import PluginRegistry, ProcessAdapter, ProcessGuardian
from openroad_platform_scheduler import JobStore, RuntimeStore, WorkflowRuntime, Worker


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


class _FixtureFactory:
    capability = "eda.rtl_to_gds"

    def __init__(self, *, plugin_id: str, expected_artifacts: tuple[str, ...] = ("report",)):
        self.plugin_id = plugin_id
        self.expected_artifacts = expected_artifacts

    def build(self, request: RTLToGDSRequest) -> TaskSpec:
        request.validate()
        return TaskSpec(
            task_id=request.task_id or "fixture-task",
            project_id=request.project_id,
            design_id=request.design_id,
            plugin_id=self.plugin_id,
            inputs={"message": "legacy job migrated", "rtl_path": request.rtl_path},
            expected_artifacts=self.expected_artifacts,
            timeout_seconds=10,
            labels=request.labels,
        )

    def validate_task(self, task: TaskSpec) -> None:
        task.validate()

    def reconfigure(self, task: TaskSpec, values):  # pragma: no cover - factory protocol completeness
        del values
        return task


def _runtime(tmp_path: Path, *, adapter: str, expected_artifacts: tuple[str, ...] = ("report",)) -> WorkflowRuntime:
    manifest = PluginManifest(
        plugin_id="fixture", plugin_version="1.0.0",
        adapter_entry=(sys.executable, str(FIXTURES / adapter)),
        capabilities=("eda.rtl_to_gds",), supported_arch=(platform.machine(),),
        input_schema={"type": "object"}, output_schema={"type": "object"},
        artifact_rules=tuple({"kind": item, "required": True} for item in expected_artifacts),
        default_timeout_seconds=10,
    )
    return WorkflowRuntime(
        RuntimeStore(tmp_path / "runtime.db"), PluginRegistry([manifest]),
        workspace_root=tmp_path / "workspaces", worker_id="runtime-worker",
        adapter=ProcessAdapter(ProcessGuardian(poll_interval=0.02, terminate_grace=0.2)),
    )


def test_legacy_worker_delegates_to_one_runtime_run_and_projects_facts(tmp_path: Path) -> None:
    rtl = tmp_path / "top.v"
    rtl.write_text("module top; endmodule\n", encoding="utf-8")
    jobs = JobStore(tmp_path / "legacy.db")
    job = jobs.submit(RunRequest(
        rtl_path=str(rtl), top="top", labels={"project_id": "migration-test"},
    ))
    runtime = _runtime(tmp_path, adapter="echo_adapter.py")
    worker = Worker(jobs, runtime=runtime, rtl_to_gds_factory=_FixtureFactory(plugin_id="fixture"))

    assert worker.run_once() is True

    projected = jobs.get(job.id)
    assert projected.status.value == "succeeded"
    assert projected.runtime_run_id is not None
    assert len(runtime.store.list_runs()) == 1
    view = runtime.describe(projected.runtime_run_id)
    assert view["run"]["status"] == "succeeded"
    assert view["stages"][0]["attempts"][0]["artifacts"][0]["kind"] == "report"
    assert projected.result == view
    assert [item["kind"] for item in jobs.events(job.id)] == [
        "submitted", "claimed", "runtime_bound", "started", "runtime_projected",
    ]


def test_legacy_cancellation_is_recorded_by_runtime_then_projected(tmp_path: Path) -> None:
    rtl = tmp_path / "top.v"
    rtl.write_text("module top; endmodule\n", encoding="utf-8")
    jobs = JobStore(tmp_path / "legacy.db")
    job = jobs.submit(RunRequest(rtl_path=str(rtl), top="top"))
    runtime = _runtime(tmp_path, adapter="sleep_adapter.py", expected_artifacts=())
    worker = Worker(
        jobs, runtime=runtime,
        rtl_to_gds_factory=_FixtureFactory(plugin_id="fixture", expected_artifacts=()),
    )
    thread = threading.Thread(target=worker.run_once)
    thread.start()
    deadline = time.monotonic() + 2
    while jobs.get(job.id).status.value != "running":
        if time.monotonic() >= deadline:
            raise AssertionError("legacy worker did not reach the Runtime execution boundary")
        time.sleep(0.01)

    jobs.request_cancel(job.id)
    thread.join(timeout=3)

    assert not thread.is_alive()
    projected = jobs.get(job.id)
    assert projected.status.value == "cancelled"
    assert projected.runtime_run_id is not None
    assert runtime.store.get_run(projected.runtime_run_id).status.value == "cancelled"
    assert "run.cancel_requested" in [
        item["event_type"] for item in runtime.store.events(projected.runtime_run_id)
    ]


def test_worker_has_no_direct_orfs_execution_dependency() -> None:
    source = ROOT / "packages/scheduler/src/openroad_platform_scheduler/worker.py"
    imports = set()
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    assert not any(name == "openroad_platform_execution" or name.startswith("openroad_platform_execution.")
                   for name in imports)
    assert "ORFSRunner" not in source.read_text(encoding="utf-8")


def test_worker_serve_keeps_legacy_polling_behavior(monkeypatch, tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, adapter="echo_adapter.py")
    worker = Worker(
        JobStore(tmp_path / "legacy.db"), runtime=runtime,
        rtl_to_gds_factory=_FixtureFactory(plugin_id="fixture"),
    )
    monkeypatch.setattr(worker, "run_once", lambda: False)

    def stop_after_one_sleep(_seconds: float) -> None:
        raise RuntimeError("stop test loop")

    monkeypatch.setattr("openroad_platform_scheduler.worker.time.sleep", stop_after_one_sleep)
    with pytest.raises(RuntimeError, match="stop test loop"):
        worker.serve(poll_seconds=0.01)
