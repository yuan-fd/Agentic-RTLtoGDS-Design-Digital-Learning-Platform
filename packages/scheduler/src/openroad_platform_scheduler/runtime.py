"""Minimal single-host Workflow Runtime over the generic plugin protocol."""

from __future__ import annotations

import platform
import re
import json
import hashlib
import socket
import time
import uuid
from pathlib import Path
from typing import Callable

from openroad_platform_contracts import RuntimeStatus, TaskSpec
from openroad_platform_contracts.protected_evaluation import ProtectedEvaluator
from openroad_platform_execution import PluginRegistry, ProcessAdapter

from .runtime_store import RuntimeRun, RuntimeStore


class WorkflowRuntime:
    def __init__(
        self,
        store: RuntimeStore,
        registry: PluginRegistry,
        *,
        workspace_root: str | Path,
        adapter: ProcessAdapter | None = None,
        worker_id: str | None = None,
        lease_seconds: int = 30,
        environment_resolver: Callable[[RuntimeRun], dict[str, str]] | None = None,
        protected_evaluator: ProtectedEvaluator | None = None,
    ):
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        self.store = store
        self.registry = registry
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.adapter = adapter or ProcessAdapter()
        self.worker_id = worker_id or f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
        self.lease_seconds = lease_seconds
        self.environment_resolver = environment_resolver
        self.protected_evaluator = protected_evaluator

    def submit(
        self,
        task: TaskSpec,
        *,
        plugin_version: str | None = None,
        capability: str | None = None,
    ) -> RuntimeRun:
        task.validate()
        if task.plugin_id is None:
            raise ValueError("P1 WorkflowRuntime only supports direct plugin TaskSpec")
        manifest = self.registry.resolve(
            task.plugin_id,
            version=plugin_version,
            capability=capability,
            arch=platform.machine(),
        )
        run, _ = self.store.submit_plugin_run(
            task, plugin_version=manifest.plugin_version
        )
        return run

    def submit_idempotent(
        self,
        task: TaskSpec,
        *,
        plugin_version: str | None = None,
        capability: str | None = None,
    ) -> RuntimeRun:
        """Submit one migration-owned task exactly once by its stable task id.

        Normal product callers should use :meth:`submit` and allocate a fresh
        task id.  This narrow entry point exists for a legacy queue projection:
        a worker can restart after Runtime accepted the task but before it
        persisted the back-reference in the old queue.  Reusing the same task
        id is safe only when the complete immutable TaskSpec is identical.
        """
        task.validate()
        if task.plugin_id is None:
            raise ValueError("P1 WorkflowRuntime only supports direct plugin TaskSpec")
        manifest = self.registry.resolve(
            task.plugin_id,
            version=plugin_version,
            capability=capability,
            arch=platform.machine(),
        )
        existing = self.store.find_run_by_task_id(task.task_id)
        if existing is not None:
            if existing.task_spec.to_dict() != task.to_dict():
                raise ValueError(
                    "Runtime task_id already exists with a different immutable TaskSpec"
                )
            stage = self.store.list_stages(existing.run_id)[0]
            if stage.plugin_version != manifest.plugin_version:
                raise ValueError("Runtime task_id already exists with a different plugin version")
            return existing
        run, _ = self.store.submit_plugin_run(task, plugin_version=manifest.plugin_version)
        return run

    def execute_once(
        self,
        run_id: str,
        *,
        on_line: Callable[[str], None] | None = None,
        external_cancel_requested: Callable[[], bool] | None = None,
    ) -> RuntimeRun:
        # A compatibility caller may observe an old cancellation request, but
        # it cannot declare an execution state.  Runtime first records the
        # request in its own store, then its normal lease/process path enforces
        # the cancellation.
        if external_cancel_requested is not None and external_cancel_requested():
            self.store.request_cancel(run_id)
        run = self.store.get_run(run_id)
        stages = self.store.list_stages(run_id)
        ready = next(
            (stage for stage in stages
             if stage.status in {RuntimeStatus.QUEUED, RuntimeStatus.RETRY_WAIT}),
            None,
        )
        if ready is None:
            return run
        manifest = self.registry.resolve(
            ready.plugin_id, version=ready.plugin_version, arch=platform.machine()
        )
        attempt_number = len(self.store.list_attempts(ready.stage_run_id)) + 1
        workspace = (
            self.workspace_root / run_id / ready.stage_run_id / f"attempt-{attempt_number}"
        )
        attempt = self.store.start_attempt(
            ready.stage_run_id,
            worker_id=self.worker_id,
            workspace=workspace,
            lease_seconds=self.lease_seconds,
        )
        pulse = _LeasePulse(
            self.store, run_id, attempt.attempt_id,
            worker_id=self.worker_id, lease_seconds=self.lease_seconds,
            external_cancel_requested=external_cancel_requested,
        )
        line_observer = _RuntimeLineObserver(
            self.store, run_id=run_id, stage_run_id=ready.stage_run_id,
            attempt_id=attempt.attempt_id,
            producer=f"adapter:{ready.plugin_id}@{ready.plugin_version}",
            downstream=on_line,
        )
        try:
            runtime_receipt: dict | None = None
            runtime_receipt_sha256: str | None = None
            environment = dict(self.environment_resolver(run) if self.environment_resolver else {})
            if ready.plugin_id == "orfs-agent":
                domain = run.task_spec.inputs.get("parameter_domain")
                if not isinstance(domain, dict) or not isinstance(domain.get("experiment_protocol"), dict):
                    raise ValueError("ORFS-Agent task lacks an immutable experiment protocol")
                workspace.mkdir(parents=True, exist_ok=True)
                receipt = workspace / "runtime_protocol_receipt.json"
                receipt.write_text(json.dumps({"schema_version": 1, "protocol": domain["experiment_protocol"],
                                               "run_id": run_id, "attempt_id": attempt.attempt_id}, sort_keys=True), encoding="utf-8")
                environment["ORFS_AGENT_PROTOCOL_RECEIPT"] = str(receipt)
                runtime_receipt_sha256 = hashlib.sha256(receipt.read_bytes()).hexdigest()
                environment["ORFS_AGENT_PROTOCOL_RECEIPT_SHA256"] = runtime_receipt_sha256
                runtime_receipt = {
                    "kind": "runtime_protocol_receipt", "path": receipt.name,
                    "metadata": {"producer": "runtime", "attempt_id": attempt.attempt_id},
                }
            execution = self.adapter.execute(
                manifest,
                run.task_spec,
                workspace=workspace,
                cancel_requested=pulse,
                on_line=line_observer,
                environment=environment,
            )
            if execution.result.status is RuntimeStatus.SUCCEEDED:
                if any(item.get("kind") == "runtime_protocol_receipt" for item in execution.artifacts):
                    raise ValueError("adapter declared Runtime-reserved artifact kind: runtime_protocol_receipt")
                if runtime_receipt is not None and runtime_receipt_sha256 != hashlib.sha256(receipt.read_bytes()).hexdigest():
                    raise ValueError("adapter modified the Runtime protocol receipt")
                runtime_artifacts = self.adapter.validate_additional_artifacts(
                    workspace, manifest, (runtime_receipt,) if runtime_receipt is not None else ())
                evaluator_artifacts: tuple[dict, ...] = ()
                if self.protected_evaluator is not None:
                    evaluator_artifacts = self.adapter.validate_additional_artifacts(
                        workspace, manifest,
                        self.protected_evaluator.evaluate(
                            manifest=manifest, task=run.task_spec,
                            workspace=str(workspace),
                        ),
                    )
                self.store.register_artifacts(
                    attempt.attempt_id, (*runtime_artifacts, *execution.artifacts, *evaluator_artifacts)
                )
                self.store.register_metrics(attempt.attempt_id, execution.result.metrics)
            self.store.finish_attempt(
                attempt.attempt_id,
                execution.result.status,
                exit_code=execution.result.exit_code,
                failure=execution.result.failure,
            )
        except Exception as exc:
            try:
                self.store.finish_attempt(
                    attempt.attempt_id,
                    RuntimeStatus.FAILED,
                    exit_code=1,
                    failure={"category": "runtime_error", "message": f"{type(exc).__name__}: {exc}"},
                )
            except ValueError as transition_error:
                # A concurrent lease monitor may already have atomically
                # changed RUNNING -> LOST.  LOST is authoritative evidence;
                # the worker must neither overwrite it nor crash the campaign
                # while attempting a second terminal transition.
                if "Invalid attempt transition lost ->" not in str(transition_error):
                    raise
        return self.store.get_run(run_id)

    def describe(self, run_id: str) -> dict:
        return self.store.describe_run(run_id)

class _LeasePulse:
    def __init__(
        self,
        store: RuntimeStore,
        run_id: str,
        attempt_id: str,
        *,
        worker_id: str,
        lease_seconds: int,
        external_cancel_requested: Callable[[], bool] | None = None,
    ):
        self.store = store
        self.run_id = run_id
        self.attempt_id = attempt_id
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.external_cancel_requested = external_cancel_requested
        self.last = 0.0

    def __call__(self) -> bool:
        if self.external_cancel_requested is not None and self.external_cancel_requested():
            self.store.request_cancel(self.run_id)
            return True
        run = self.store.get_run(self.run_id)
        if run.status is RuntimeStatus.CANCEL_REQUESTED:
            return True
        now = time.monotonic()
        interval = max(1.0, self.lease_seconds / 3)
        if now - self.last >= interval:
            self.store.heartbeat(
                self.attempt_id,
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
            )
            self.last = now
        return False


class _RuntimeLineObserver:
    """Convert the allowlisted ORFS stdout protocol into durable Runtime events."""

    START = re.compile(r"^\[orfs-stage-start\] (synth|floorplan|place|cts|route|finish)$")
    FINISH = re.compile(
        r"^\[orfs-stage\] (synth|floorplan|place|cts|route|finish) "
        r"(succeeded|failed|cancelled) (\d+(?:\.\d+)?)s$"
    )

    def __init__(self, store: RuntimeStore, *, run_id: str, stage_run_id: str,
                 attempt_id: str, producer: str,
                 downstream: Callable[[str], None] | None):
        self.store = store
        self.run_id = run_id
        self.stage_run_id = stage_run_id
        self.attempt_id = attempt_id
        self.producer = producer
        self.downstream = downstream
        self.started: set[str] = set()
        self.finished: set[str] = set()

    def __call__(self, line: str) -> None:
        if self.downstream is not None:
            self.downstream(line)
        start = self.START.fullmatch(line.strip())
        if start and start.group(1) not in self.started:
            stage = start.group(1)
            self.started.add(stage)
            self.store.record_event(
                self.run_id, "tool.stage.started", {"tool_stage": stage},
                stage_run_id=self.stage_run_id, attempt_id=self.attempt_id,
                producer=self.producer,
            )
            return
        finish = self.FINISH.fullmatch(line.strip())
        if finish and finish.group(1) not in self.finished:
            stage, status, seconds = finish.groups()
            self.finished.add(stage)
            self.store.record_event(
                self.run_id, "tool.stage.finished",
                {"tool_stage": stage, "status": status, "seconds": float(seconds)},
                stage_run_id=self.stage_run_id, attempt_id=self.attempt_id,
                producer=self.producer,
            )
