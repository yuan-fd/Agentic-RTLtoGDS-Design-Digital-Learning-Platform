import importlib.util
import hashlib
import json
from pathlib import Path
import sqlite3


def _module():
    path = Path(__file__).resolve().parents[1] / "scripts/aggregate_industrial_dse_campaign.py"
    spec = importlib.util.spec_from_file_location("industrial_aggregation", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_explicitly_excluded_cell_is_never_eligible(tmp_path):
    (tmp_path / "EXCLUDED_FROM_FORMAL_STUDY.json").write_text(json.dumps({
        "excluded": True, "reason": "unit mismatch",
    }))
    row = _module().aggregate_cell(tmp_path, protocol_digest="a" * 64)
    assert row["eligible"] is False
    assert any("explicitly excluded" in item for item in row["errors"])


def test_failed_native_controller_is_not_an_optimizer_outcome(tmp_path):
    records = [{"path": "runner.py", "sha256": "a" * 64}]
    digest = hashlib.sha256(json.dumps(
        records, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    (tmp_path / "controller-source-snapshot.json").write_text(json.dumps({
        "digest": digest, "file_count": 1, "files": records,
    }))
    environment = {"schema_version": 1, "kind": "test-environment"}
    environment["fingerprint"] = hashlib.sha256(json.dumps(
        environment, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    (tmp_path / "python-environment.json").write_text(json.dumps(environment))
    (tmp_path / "cell-manifest.json").write_text(json.dumps({
        "frozen_study_protocol_digest": "p", "common_evaluator_schema": 3,
        "toolchain_validated": True, "toolchain_validation_fingerprint": "tool",
        "toolchain_lock_sha256": "lock", "controller_source_snapshot_sha256": digest,
        "paired_or_seeds": [101, 211, 307], "ablation": "none",
        "study_mode": "paper",
        "python_environment_fingerprint": environment["fingerprint"],
    }))
    (tmp_path / "toolchain-validation.json").write_text(json.dumps({
        "validated": True, "validation_fingerprint": "tool",
        "lock_sha256": "lock",
    }))
    (tmp_path / "checkpoint-export.json").write_text(json.dumps({"state": {
        "status": "failed", "round": 0, "max_rounds": 1,
        "history": [], "repetitions": 3,
        "replica_or_seeds": [101, 211, 307], "ablation_id": "none",
    }}))
    row = _module().aggregate_cell(tmp_path, protocol_digest="p")
    assert row["eligible"] is False
    assert any("not an optimizer outcome" in item for item in row["errors"])


def test_runtime_cost_counts_parallel_worker_time_and_unstarted_cancellation(tmp_path):
    database = tmp_path / "runtime.db"
    with sqlite3.connect(database) as connection:
        connection.execute("""CREATE TABLE runtime_runs (
            run_id TEXT, status TEXT, task_spec_json TEXT, created_at TEXT,
            started_at TEXT, ended_at TEXT)""")
        task = json.dumps({"parameters": {"target_stage": "finish"},
                           "labels": {"fidelity": "full"}})
        connection.executemany(
            "INSERT INTO runtime_runs VALUES (?, ?, ?, ?, ?, ?)", [
                ("run-a", "succeeded", task, "2026-01-01T00:00:00+00:00",
                 "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:10+00:00"),
                ("run-b", "cancelled", task, "2026-01-01T00:00:01+00:00",
                 None, None),
            ])
    result = _module()._runtime_cost_summary(tmp_path)
    assert result["run_count"] == 2
    assert result["verified_duration_count"] == 2
    assert result["missing_duration_count"] == 0
    assert result["total_run_wall_seconds"] == 10.0
    assert result["by_target_stage"]["finish"]["run_count"] == 2
