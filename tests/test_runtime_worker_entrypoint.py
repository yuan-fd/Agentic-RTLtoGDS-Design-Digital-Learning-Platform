from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from apps.api.app import ApiState
from openroad_platform_contracts import TaskSpec
from scripts.run_dse_controller_worker import _next_pipeline
from scripts.run_runtime_worker import _oldest_ready_run


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_worker_once_advances_the_workflow_runtime_queue(tmp_path: Path) -> None:
    state = ApiState(
        tmp_path / "platform.db", tmp_path / "uploads", tmp_path / "orfs",
        design_root=tmp_path / "designs", legacy_root=tmp_path / "legacy",
        yosys_bin=ROOT.parent / "bin" / "yosys",
        runtime_db_path=tmp_path / "runtime.db",
        optimization_db_path=tmp_path / "optimization.db",
    )
    submitted = state.submit_edacraft_smoke("edacode")
    run_id = submitted["run"]["run"]["run_id"]

    completed = subprocess.run([
        sys.executable, str(ROOT / "scripts/run_runtime_worker.py"), "--once",
        "--db", str(tmp_path / "platform.db"),
        "--upload-root", str(tmp_path / "uploads"),
        "--design-root", str(tmp_path / "designs"),
        "--legacy-root", str(tmp_path / "legacy"),
        "--runtime-db", str(tmp_path / "runtime.db"),
        "--optimization-db", str(tmp_path / "optimization.db"),
        "--orfs-root", str(tmp_path / "orfs"),
        "--heartbeat", str(tmp_path / "runtime-worker.heartbeat.json"),
    ], cwd=ROOT, text=True, capture_output=True, timeout=60, check=False)

    assert completed.returncode == 0, completed.stderr
    assert state.runtime_store.get_run(run_id).status.value == "succeeded"


def test_generic_worker_does_not_race_dse_controller_owned_runs(tmp_path: Path) -> None:
    state = ApiState(
        tmp_path / "platform.db", tmp_path / "uploads", tmp_path / "orfs",
        design_root=tmp_path / "designs", legacy_root=tmp_path / "legacy",
        runtime_db_path=tmp_path / "runtime.db", load_taiwei_plugin=False,
    )
    dse = state.runtime.submit(TaskSpec(
        "dse-task", "project", "design", plugin_id="orfs",
        inputs={"rtl": {"path": "/tmp/a.v", "sha256": "a" * 64}, "top": "top"},
        parameters={"platform": "nangate45", "target_stage": "finish"},
        labels={"v2_pipeline_id": "pipeline-one"},
    ))
    ordinary = state.runtime.submit(TaskSpec(
        "ordinary-task", "project", "design", plugin_id="orfs",
        inputs={"rtl": {"path": "/tmp/a.v", "sha256": "a" * 64}, "top": "top"},
        parameters={"platform": "nangate45", "target_stage": "finish"},
    ))
    assert _oldest_ready_run(state).run_id == ordinary.run_id
    assert state.runtime_store.get_run(dse.run_id).status.value == "queued"


def test_dse_worker_discovers_only_nonterminal_durable_checkpoints(tmp_path: Path) -> None:
    state = ApiState(
        tmp_path / "platform.db", tmp_path / "uploads", tmp_path / "orfs",
        design_root=tmp_path / "designs", legacy_root=tmp_path / "legacy",
        runtime_db_path=tmp_path / "runtime.db", load_taiwei_plugin=False,
    )
    active = state.pipeline_checkpoints.create_or_get(
        pipeline_kind="bo-gp-closed-loop-v2", subject_id="active", owner_id=None,
        initial_state={"status": "baseline_running"})
    done = state.pipeline_checkpoints.create_or_get(
        pipeline_kind="bo-gp-closed-loop-v2", subject_id="done", owner_id=None,
        initial_state={"status": "completed"})
    assert done["pipeline_id"] != active["pipeline_id"]
    assert _next_pipeline(state)["pipeline_id"] == active["pipeline_id"]
