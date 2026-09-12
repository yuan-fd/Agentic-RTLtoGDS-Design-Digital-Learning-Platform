from __future__ import annotations

import multiprocessing
import platform
import sys
from pathlib import Path

import pytest

from openroad_platform_contracts import PluginManifest, RuntimeStatus, TaskSpec
from openroad_platform_execution import PluginRegistry, ProcessAdapter
from openroad_platform_scheduler import RuntimeStore, WorkflowRuntime


FIXTURE = Path(__file__).parent / "fixtures" / "echo_adapter.py"


def _registry() -> PluginRegistry:
    return PluginRegistry([PluginManifest(
        plugin_id="echo", plugin_version="1.0.0",
        adapter_entry=(sys.executable, str(FIXTURE)), capabilities=("test.echo",),
        supported_arch=(platform.machine(),), input_schema={"type": "object"},
        output_schema={"type": "object"},
        artifact_rules=({"kind": "report", "required": True},),
        default_timeout_seconds=10,
    )])


def _task() -> TaskSpec:
    return TaskSpec(
        task_id="claim-race", project_id="project", design_id="design",
        plugin_id="echo", inputs={"message": "claim race"},
        expected_artifacts=("report",), timeout_seconds=10,
    )


class _CountingAdapter(ProcessAdapter):
    def __init__(self, count):
        super().__init__()
        self.count = count

    def execute(self, *args, **kwargs):
        with self.count.get_lock():
            self.count.value += 1
        return super().execute(*args, **kwargs)


def _race_worker(db_path, workspace_root, run_id, barrier, count, results):
    runtime = WorkflowRuntime(
        RuntimeStore(db_path), _registry(), adapter=_CountingAdapter(count),
        workspace_root=workspace_root, worker_id=f"race-{multiprocessing.current_process().pid}",
    )
    original = runtime.store.start_attempt

    def synchronized_start(*args, **kwargs):
        barrier.wait(timeout=15)
        return original(*args, **kwargs)

    runtime.store.start_attempt = synchronized_start
    try:
        result = runtime.execute_once(run_id)
        results.put(("ok", result.status.value))
    except Exception as exc:  # surfaced to the parent with no implementation coupling
        results.put(("error", type(exc).__name__, str(exc)))


@pytest.mark.skipif("fork" not in multiprocessing.get_all_start_methods(), reason="requires process fork")
def test_execute_once_claims_a_ready_stage_once_across_processes(tmp_path):
    context = multiprocessing.get_context("fork")
    store = RuntimeStore(tmp_path / "runtime.db")
    runtime = WorkflowRuntime(store, _registry(), workspace_root=tmp_path / "workspaces")
    run = runtime.submit(_task(), capability="test.echo")
    barrier = context.Barrier(4)
    count = context.Value("i", 0)
    results = context.Queue()
    processes = [context.Process(
        target=_race_worker,
        args=(str(tmp_path / "runtime.db"), str(tmp_path / "workspaces"),
              run.run_id, barrier, count, results),
    ) for _ in range(4)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(30)
        assert process.exitcode == 0

    outcomes = [results.get(timeout=2) for _ in processes]
    assert all(outcome[0] == "ok" for outcome in outcomes), outcomes
    assert count.value == 1

    final = WorkflowRuntime(store, _registry(), workspace_root=tmp_path / "workspaces").describe(run.run_id)
    assert final["run"]["status"] == RuntimeStatus.SUCCEEDED.value
    attempts = final["stages"][0]["attempts"]
    assert len(attempts) == 1
    assert attempts[0]["status"] == RuntimeStatus.SUCCEEDED.value
    assert (Path(attempts[0]["workspace"]) / "report.json").is_file()
