from __future__ import annotations

import platform
import sys
import threading
import time
import json
from pathlib import Path

from openroad_platform_contracts import PluginManifest, RuntimeStatus, TaskSpec
from openroad_platform_execution import PluginRegistry, ProcessAdapter, ProcessGuardian
from openroad_platform_scheduler import RuntimeStore, WorkflowRuntime


FIXTURES = Path(__file__).parent / "fixtures"


def registry(script: str) -> PluginRegistry:
    return PluginRegistry([PluginManifest(
        plugin_id="echo",
        plugin_version="1.0.0",
        adapter_entry=(sys.executable, str(FIXTURES / script)),
        capabilities=("test.echo",),
        supported_arch=(platform.machine(),),
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        artifact_rules=({"kind": "report", "required": True},),
        default_timeout_seconds=10,
    )])


def task(*, timeout_seconds: int = 10) -> TaskSpec:
    return TaskSpec(
        task_id="task-e2e", project_id="project", design_id="design",
        plugin_id="echo", inputs={"message": "runtime owns status"},
        expected_artifacts=("report",), timeout_seconds=timeout_seconds,
    )


class _RecordingEvaluator:
    """A platform evaluator double: it only adds workspace-local evidence."""

    def __init__(self):
        self.calls = []

    def evaluate(self, *, manifest, task, workspace):
        self.calls.append((manifest.plugin_id, task.task_id, workspace))
        path = Path(workspace) / "protected-evaluation.json"
        path.write_text(json.dumps({"canonical": True}), encoding="utf-8")
        return ({
            "kind": "report", "path": "protected-evaluation.json",
            "metadata": {"producer": "test-protected-evaluator"},
        },)


def test_runtime_executes_full_contract_attempt_evidence_chain(tmp_path):
    store = RuntimeStore(tmp_path / "runtime.db")
    runtime = WorkflowRuntime(
        store, registry("echo_adapter.py"),
        workspace_root=tmp_path / "workspaces", worker_id="test-worker",
    )
    run = runtime.submit(task(), capability="test.echo")
    completed = runtime.execute_once(run.run_id)

    assert completed.status is RuntimeStatus.SUCCEEDED
    view = runtime.describe(run.run_id)
    attempt = view["stages"][0]["attempts"][0]
    assert attempt["status"] == "succeeded"
    assert attempt["artifacts"][0]["store_key"] == "report.json"
    assert attempt["metrics"][0]["name"] == "messages"
    assert [event["event_type"] for event in view["events"]] == [
        "run.accepted", "stage.ready", "attempt.started",
        "artifact.registered", "metric.recorded", "attempt.finished", "run.finished",
    ]


def test_runtime_rejects_adapter_that_tampers_orfs_protocol_receipt(tmp_path):
    protocol = {"rtl_sha256": "a" * 64, "pdk_id": "asap7", "toolchain_id": "openroad",
                "sdc_sha256": "b" * 64, "evaluator_version": "v1", "seed_policy": "fixed",
                "timing": {"clock_period_ns": 1.0, "clock_uncertainty_ns": .1, "io_delay_ns": .2}}
    manifest = PluginManifest(plugin_id="orfs-agent", plugin_version="test",
        adapter_entry=(sys.executable, str(FIXTURES / "tamper_receipt_adapter.py")), capabilities=("test.orfs",),
        supported_arch=(platform.machine(),), input_schema={"type": "object"}, output_schema={"type": "object"},
        artifact_rules=({"kind": "report", "required": True}, {"kind": "runtime_protocol_receipt", "required": False}))
    task = TaskSpec(task_id="tamper-receipt", project_id="p", design_id="d", plugin_id="orfs-agent",
        inputs={"parameter_domain": {"experiment_protocol": protocol}}, expected_artifacts=("report",))
    runtime = WorkflowRuntime(RuntimeStore(tmp_path / "runtime.db"), PluginRegistry([manifest]), workspace_root=tmp_path / "work")
    run = runtime.submit(task, capability="test.orfs")
    assert runtime.execute_once(run.run_id).status is RuntimeStatus.FAILED


def test_runtime_rejects_adapter_claiming_its_reserved_receipt_artifact(tmp_path):
    protocol = {"rtl_sha256":"a"*64,"pdk_id":"asap7","toolchain_id":"openroad","sdc_sha256":"b"*64,"evaluator_version":"v1","seed_policy":"fixed","timing":{"clock_period_ns":1.0,"clock_uncertainty_ns":.1,"io_delay_ns":.2}}
    manifest = PluginManifest(plugin_id="orfs-agent", plugin_version="test", adapter_entry=(sys.executable, str(FIXTURES / "claim_receipt_adapter.py")), capabilities=("test.orfs",), supported_arch=(platform.machine(),), input_schema={"type":"object"}, output_schema={"type":"object"}, artifact_rules=({"kind":"report","required":True},{"kind":"runtime_protocol_receipt","required":False}))
    task = TaskSpec(task_id="claim-receipt", project_id="p", design_id="d", plugin_id="orfs-agent", inputs={"parameter_domain":{"experiment_protocol":protocol}}, expected_artifacts=("report",))
    runtime = WorkflowRuntime(RuntimeStore(tmp_path / "runtime.db"), PluginRegistry([manifest]), workspace_root=tmp_path / "work")
    run = runtime.submit(task, capability="test.orfs")
    assert runtime.execute_once(run.run_id).status is RuntimeStatus.FAILED
    assert not runtime.describe(run.run_id)["stages"][0]["attempts"][0]["artifacts"]


def test_runtime_registers_post_execution_evaluator_evidence_after_adapter_success(tmp_path):
    store = RuntimeStore(tmp_path / "runtime.db")
    evaluator = _RecordingEvaluator()
    runtime = WorkflowRuntime(
        store, registry("echo_adapter.py"), protected_evaluator=evaluator,
        workspace_root=tmp_path / "workspaces", worker_id="test-worker",
    )

    run = runtime.submit(task(), capability="test.echo")
    completed = runtime.execute_once(run.run_id)
    attempt = runtime.describe(run.run_id)["stages"][0]["attempts"][0]

    assert completed.status is RuntimeStatus.SUCCEEDED
    assert evaluator.calls and evaluator.calls[0][:2] == ("echo", "task-e2e")
    artifact = next(item for item in attempt["artifacts"]
                    if item["store_key"] == "protected-evaluation.json")
    path = Path(attempt["workspace"]) / artifact["store_key"]
    assert artifact["metadata"]["producer"] == "test-protected-evaluator"
    assert artifact["sha256"] == __import__("hashlib").sha256(path.read_bytes()).hexdigest()


def test_runtime_rejects_evaluator_artifact_outside_workspace(tmp_path):
    class UnsafeEvaluator:
        def evaluate(self, **_kwargs):
            return ({"kind": "report", "path": "../outside.json"},)

    runtime = WorkflowRuntime(
        RuntimeStore(tmp_path / "runtime.db"), registry("echo_adapter.py"),
        protected_evaluator=UnsafeEvaluator(),
        workspace_root=tmp_path / "workspaces", worker_id="test-worker",
    )
    run = runtime.submit(task(), capability="test.echo")

    assert runtime.execute_once(run.run_id).status is RuntimeStatus.FAILED
    attempt = runtime.describe(run.run_id)["stages"][0]["attempts"][0]
    assert attempt["failure"]["category"] == "runtime_error"
    assert all(item["store_key"] != "../outside.json" for item in attempt["artifacts"])


def test_runtime_idempotent_submission_reuses_only_the_same_immutable_task(tmp_path):
    runtime = WorkflowRuntime(
        RuntimeStore(tmp_path / "runtime.db"), registry("echo_adapter.py"),
        workspace_root=tmp_path / "workspaces", worker_id="test-worker",
    )
    first = runtime.submit_idempotent(task(), capability="test.echo")
    again = runtime.submit_idempotent(task(), capability="test.echo")

    assert again.run_id == first.run_id
    assert len(runtime.store.list_runs()) == 1


def test_runtime_injects_ephemeral_credential_without_persisting_value(tmp_path):
    secret = "test-secret-must-not-persist"
    manifest = PluginManifest("echo", "1.0.0", (sys.executable, str(FIXTURES / "credential_probe_adapter.py")),
                              ("test.echo",), (platform.machine(),), {"type":"object"}, {"type":"object"},
                              artifact_rules=({"kind":"report","required":True},))
    runtime = WorkflowRuntime(RuntimeStore(tmp_path / "runtime.db"), PluginRegistry([manifest]),
                              workspace_root=tmp_path / "workspaces",
                              environment_resolver=lambda run: {"OPENROUTER_API_KEY": secret})
    run = runtime.submit(task()); assert secret not in str(run.task_spec.to_dict())
    assert runtime.execute_once(run.run_id).status is RuntimeStatus.SUCCEEDED
    workspace = Path(runtime.describe(run.run_id)["stages"][0]["attempts"][0]["workspace"])
    assert runtime.store.metrics(runtime.store.list_attempts(runtime.store.list_stages(run.run_id)[0].stage_run_id)[0].attempt_id)[0]["value"] == 1
    assert secret not in (workspace / "adapter_request.json").read_text()
    assert secret not in (workspace / "adapter.log").read_text()


def test_runtime_rejects_plugin_success_when_artifact_escapes_workspace(tmp_path):
    store = RuntimeStore(tmp_path / "runtime.db")
    runtime = WorkflowRuntime(
        store, registry("bad_artifact_adapter.py"),
        workspace_root=tmp_path / "workspaces", worker_id="test-worker",
    )
    run = runtime.submit(task())
    failed = runtime.execute_once(run.run_id)

    assert failed.status is RuntimeStatus.FAILED
    attempt = runtime.describe(run.run_id)["stages"][0]["attempts"][0]
    assert attempt["failure"]["category"] == "protocol_error"
    assert attempt["artifacts"] == []


def test_runtime_records_structured_timeout_and_terminal_event(tmp_path):
    store = RuntimeStore(tmp_path / "runtime.db")
    runtime = WorkflowRuntime(
        store, registry("sleep_adapter.py"), workspace_root=tmp_path / "workspaces",
        adapter=ProcessAdapter(ProcessGuardian(
            poll_interval=0.02, terminate_grace=0.2,
        )),
        worker_id="test-worker",
    )
    run = runtime.submit(task(timeout_seconds=1))

    completed = runtime.execute_once(run.run_id)
    view = runtime.describe(run.run_id)

    assert completed.status is RuntimeStatus.FAILED
    assert completed.terminal_reason == "timed_out"
    attempt = view["stages"][0]["attempts"][0]
    assert attempt["status"] == "timed_out"
    assert attempt["failure"]["category"] == "timeout"
    assert view["events"][-2]["payload"]["status"] == "timed_out"
    assert view["events"][-1]["event_type"] == "run.finished"


def test_runtime_cancels_live_process_after_durable_request(tmp_path):
    store = RuntimeStore(tmp_path / "runtime.db")
    runtime = WorkflowRuntime(
        store, registry("sleep_adapter.py"), workspace_root=tmp_path / "workspaces",
        adapter=ProcessAdapter(ProcessGuardian(
            poll_interval=0.02, terminate_grace=0.2,
        )),
        worker_id="test-worker",
    )
    run = runtime.submit(task())
    worker = threading.Thread(target=runtime.execute_once, args=(run.run_id,))
    worker.start()
    deadline = time.monotonic() + 2
    while not store.list_attempts(store.list_stages(run.run_id)[0].stage_run_id):
        if time.monotonic() >= deadline:
            raise AssertionError("runtime did not start an attempt")
        time.sleep(0.01)

    store.request_cancel(run.run_id)
    worker.join(timeout=3)
    view = runtime.describe(run.run_id)

    assert not worker.is_alive()
    assert view["run"]["status"] == "cancelled"
    attempt = view["stages"][0]["attempts"][0]
    assert attempt["status"] == "cancelled"
    assert attempt["failure"]["category"] == "cancelled"
    assert "run.cancel_requested" in [item["event_type"] for item in view["events"]]
