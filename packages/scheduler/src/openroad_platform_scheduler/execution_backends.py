"""Pluggable local and Ray execution backends for durable Runtime runs."""

from __future__ import annotations

import os
import socket
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Protocol, Sequence

from openroad_platform_contracts import PluginManifest, TERMINAL_RUNTIME_STATUSES
from openroad_platform_execution import PluginRegistry, ProcessAdapter

from .runtime import WorkflowRuntime
from .runtime_store import RuntimeStore


class ParallelExecutionBackend(Protocol):
    backend_id: str

    def run_bound(self, runtime: WorkflowRuntime, run_ids: Sequence[str], *,
                  max_parallel: int) -> dict[str, Any]: ...


class LocalThreadExecutionBackend:
    backend_id = "local-thread-v1"

    def run_bound(self, runtime: WorkflowRuntime, run_ids: Sequence[str], *,
                  max_parallel: int) -> dict[str, Any]:
        pending = [run_id for run_id in run_ids
                   if runtime.store.get_run(run_id).status not in TERMINAL_RUNTIME_STATUSES]
        with ThreadPoolExecutor(max_workers=max_parallel) as pool:
            for future in [pool.submit(runtime.execute_once, run_id) for run_id in pending]:
                future.result()
        return {"backend_id": self.backend_id, "submitted": len(pending),
                "max_parallel": max_parallel, "distributed": False}


@dataclass(frozen=True)
class _RayRuntimeSpec:
    runtime_db: str
    workspace_root: str
    manifests: tuple[dict[str, Any], ...]
    lease_seconds: int


def _ray_execute_runtime(spec: _RayRuntimeSpec, run_id: str) -> dict[str, Any]:
    """Ray worker entry point; reconstruct only immutable/runtime-safe state."""
    worker_id = f"ray-{socket.gethostname()}-{os.getpid()}"
    runtime = WorkflowRuntime(
        RuntimeStore(spec.runtime_db),
        PluginRegistry(PluginManifest.from_dict(item) for item in spec.manifests),
        workspace_root=spec.workspace_root, adapter=ProcessAdapter(),
        worker_id=worker_id, lease_seconds=spec.lease_seconds,
    )
    result = runtime.execute_once(run_id)
    return {"run_id": run_id, "status": result.status.value,
            "worker_id": worker_id}


class RayExecutionBackend:
    """Ray task backend over the same durable Runtime identities.

    A local Ray cluster is distributed across worker processes. Passing an
    external ``address`` connects the same plugin contract to a preconfigured
    Ray cluster whose workers can reach the Runtime DB and workspace paths.
    """

    backend_id = "ray-runtime-v1"

    def __init__(self, *, address: str | None = None):
        self.address = address

    def run_bound(self, runtime: WorkflowRuntime, run_ids: Sequence[str], *,
                  max_parallel: int) -> dict[str, Any]:
        if type(runtime.adapter) is not ProcessAdapter:
            raise ValueError("Ray backend requires the versioned ProcessAdapter")
        if runtime.environment_resolver is not None:
            environments = [runtime.environment_resolver(runtime.store.get_run(run_id))
                            for run_id in run_ids]
            if any(environment for environment in environments):
                raise ValueError(
                    "Ray backend rejects dynamic per-process environment injection"
                )
        try:
            import ray
        except ImportError as exc:
            raise RuntimeError("Ray execution backend is not installed") from exc
        if not ray.is_initialized():
            options: dict[str, Any] = {
                "include_dashboard": False, "log_to_driver": False,
                "ignore_reinit_error": True,
                # Source-checkout deployments (including CI) inject the five
                # package roots into sys.path rather than installing a wheel.
                # Ray workers need the same immutable code locations to
                # deserialize this module. Production clusters should install
                # the pinned wheel at these paths on every node.
                "runtime_env": {"env_vars": {
                    "PYTHONPATH": os.pathsep.join(
                        str(Path(item).resolve()) for item in sys.path if item
                    )
                }},
            }
            if self.address:
                options["address"] = self.address
            else:
                options["num_cpus"] = max_parallel
            ray.init(**options)
        pending = [run_id for run_id in run_ids
                   if runtime.store.get_run(run_id).status not in TERMINAL_RUNTIME_STATUSES]
        spec = _RayRuntimeSpec(
            runtime_db=str(runtime.store.path),
            workspace_root=str(runtime.workspace_root),
            manifests=tuple(item.to_dict() for item in runtime.registry.list()),
            lease_seconds=runtime.lease_seconds,
        )
        remote_execute = ray.remote(num_cpus=1)(_ray_execute_runtime)
        results = ray.get([remote_execute.remote(spec, run_id) for run_id in pending])
        return {
            "backend_id": self.backend_id, "submitted": len(pending),
            "max_parallel": max_parallel, "distributed": True,
            "ray_address": str(ray.get_runtime_context().gcs_address),
            "worker_ids": sorted({item["worker_id"] for item in results}),
        }


class ExecutionBackendRegistry:
    def __init__(self, backends: Iterable[ParallelExecutionBackend] = ()):
        self._backends = {item.backend_id: item for item in backends}

    def resolve(self, backend_id: str) -> ParallelExecutionBackend:
        try:
            return self._backends[backend_id]
        except KeyError as exc:
            raise KeyError(f"Unknown execution backend: {backend_id}") from exc


def default_execution_backend_registry(*, ray_address: str | None = None) \
        -> ExecutionBackendRegistry:
    return ExecutionBackendRegistry((
        LocalThreadExecutionBackend(), RayExecutionBackend(address=ray_address),
    ))
