from __future__ import annotations

import socket
import time
import uuid
from pathlib import Path

from openroad_platform_contracts import RTLToGDSFactory, RTLToGDSRequest, RuntimeStatus

from .store import JobStore
from .runtime import WorkflowRuntime


class Worker:
    def __init__(
        self,
        store: JobStore,
        *,
        runtime: WorkflowRuntime,
        rtl_to_gds_factory: RTLToGDSFactory,
        worker_id: str | None = None,
    ):
        self.store = store
        self.runtime = runtime
        self.rtl_to_gds_factory = rtl_to_gds_factory
        self.worker_id = worker_id or f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"

    def run_once(self) -> bool:
        job = self.store.claim_next(self.worker_id)
        if job is None:
            return False
        try:
            if self.store.cancel_requested(job.id):
                self.store.mark_cancelled(job.id)
                return True
            runtime_run = self._runtime_run_for(job)
            self.store.bind_runtime_run(job.id, runtime_run.run_id)
            if runtime_run.status in _RUNTIME_TERMINAL:
                self.store.project_runtime(job.id, self.runtime.describe(runtime_run.run_id))
                return True
            if self.store.get(job.id).status.value == "preparing":
                self.store.mark_running(job.id)
            completed = self.runtime.execute_once(
                runtime_run.run_id,
                external_cancel_requested=lambda: self.store.cancel_requested(job.id),
            )
            if completed.status in _RUNTIME_TERMINAL:
                self.store.project_runtime(job.id, self.runtime.describe(completed.run_id))
        except Exception as exc:
            self.store.fail(job.id, f"{type(exc).__name__}: {exc}")
        return True

    def _runtime_run_for(self, job):
        if job.runtime_run_id:
            return self.runtime.store.get_run(job.runtime_run_id)
        request = job.request
        design_id = request.top or Path(request.rtl_path).stem or "legacy_design"
        task = self.rtl_to_gds_factory.build(RTLToGDSRequest(
            rtl_path=request.rtl_path,
            project_id=_identifier(request.labels.get("project_id") or "legacy"),
            design_id=_identifier(design_id),
            top=request.top,
            task_id=f"legacy:{job.id}",
            labels={**request.labels, "legacy_job_id": job.id,
                    "legacy_projection": "true"},
            options={
                "clock": request.clock,
                "platform_name": request.platform,
                "target_stage": request.target_stage.value,
                "clock_period_ns": request.clock_period_ns,
                "core_utilization_pct": request.core_utilization_pct,
                "place_density": request.place_density,
                "or_seed": request.or_seed,
                "minimum_die_size_um": request.minimum_die_size_um,
                "stage_timeout_seconds": request.stage_timeout_seconds,
                "flow_parameters": request.flow_parameters,
                "rtl_files": request.rtl_files,
                "rtl_root": request.rtl_root,
                "rtl_include_dirs": request.rtl_include_dirs,
                "synth_hdl_frontend": request.synth_hdl_frontend,
                "design_options": request.design_options,
                "sdc_path": request.sdc_path,
            },
        ))
        return self.runtime.submit_idempotent(task, capability="eda.rtl_to_gds")

    def serve(self, *, poll_seconds: float = 1.0) -> None:
        while True:
            if not self.run_once():
                time.sleep(poll_seconds)


_RUNTIME_TERMINAL = {
    RuntimeStatus.SUCCEEDED, RuntimeStatus.FAILED, RuntimeStatus.CANCELLED,
    RuntimeStatus.TIMED_OUT, RuntimeStatus.LOST,
}


def _identifier(value: str) -> str:
    sanitized = "".join(character if character.isalnum() or character in "_.:-" else "_"
                        for character in value.strip())[:128]
    return sanitized if sanitized and sanitized[0].isalnum() else "legacy"
