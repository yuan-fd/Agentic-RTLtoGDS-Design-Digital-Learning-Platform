from __future__ import annotations

import platform
import sys
from pathlib import Path

import pytest

from openroad_platform_contracts import PluginManifest, RuntimeStatus, TaskSpec
from openroad_platform_execution import PluginRegistry
from openroad_platform_scheduler import (
    RayExecutionBackend, RuntimeStore, WorkflowRuntime,
)


ADAPTER = Path(__file__).parent / "fixtures" / "echo_adapter.py"


def _runtime(tmp_path, *, environment_resolver=None):
    manifest = PluginManifest(
        "echo", "1.0.0", (sys.executable, str(ADAPTER)), ("test.echo",),
        (platform.machine(),), {}, {},
        artifact_rules=({"kind": "report", "required": True},),
    )
    return WorkflowRuntime(
        RuntimeStore(tmp_path / "runtime.db"), PluginRegistry([manifest]),
        workspace_root=tmp_path / "runs",
        environment_resolver=environment_resolver,
    )


def test_ray_backend_executes_durable_runs_across_worker_processes(tmp_path):
    ray = pytest.importorskip("ray")
    runtime = _runtime(tmp_path)
    run_ids = [runtime.submit(TaskSpec(
        f"task-{index}", "project", "design", plugin_id="echo",
        inputs={"message": str(index)},
    )).run_id for index in range(4)]
    try:
        evidence = RayExecutionBackend().run_bound(
            runtime, run_ids, max_parallel=2)
        assert evidence["distributed"] is True
        assert evidence["backend_id"] == "ray-runtime-v1"
        assert evidence["submitted"] == 4
        assert len(evidence["worker_ids"]) >= 2
        assert all(runtime.store.get_run(run_id).status is RuntimeStatus.SUCCEEDED
                   for run_id in run_ids)
        attempt_workers = {
            attempt.worker_id
            for run_id in run_ids
            for stage in runtime.store.list_stages(run_id)
            for attempt in runtime.store.list_attempts(stage.stage_run_id)
        }
        assert attempt_workers == set(evidence["worker_ids"])
    finally:
        if ray.is_initialized():
            ray.shutdown()


def test_ray_backend_rejects_dynamic_environment_injection(tmp_path):
    runtime = _runtime(tmp_path, environment_resolver=lambda _run: {"SECRET": "x"})
    run_id = runtime.submit(TaskSpec(
        "task-secret", "project", "design", plugin_id="echo",
        inputs={"message": "x"},
    )).run_id
    with pytest.raises(ValueError, match="dynamic.*environment"):
        RayExecutionBackend().run_bound(runtime, [run_id], max_parallel=1)
