from __future__ import annotations

import os
import subprocess
import sys

from openroad_platform_contracts import RunRequest, RunStatus
from openroad_platform_scheduler import JobStore


def test_queue_survives_store_reopen_and_claim_is_exclusive(tmp_path):
    rtl = tmp_path / "top.v"
    rtl.write_text("module top; endmodule\n")
    db = tmp_path / "platform.db"
    first = JobStore(db)
    job = first.submit(RunRequest(rtl_path=str(rtl), top="top"))

    reopened = JobStore(db)
    assert reopened.get(job.id).status is RunStatus.QUEUED
    claimed = reopened.claim_next("worker-a")
    assert claimed is not None and claimed.id == job.id
    assert reopened.claim_next("worker-b") is None
    assert JobStore(db).get(job.id).status is RunStatus.PREPARING


def test_queued_job_can_be_cancelled_without_worker(tmp_path):
    rtl = tmp_path / "top.v"
    rtl.write_text("module top; endmodule\n")
    store = JobStore(tmp_path / "platform.db")
    job = store.submit(RunRequest(rtl_path=str(rtl)))
    cancelled = store.request_cancel(job.id)
    assert cancelled.status is RunStatus.CANCELLED
    assert [event["kind"] for event in store.events(job.id)] == ["submitted", "cancelled"]


def test_concurrent_store_initialization_is_serialized(tmp_path):
    db = tmp_path / "platform.db"
    code = "from openroad_platform_scheduler import JobStore; JobStore(__import__('sys').argv[1])"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(sys.path)
    processes = [subprocess.Popen([sys.executable, "-c", code, str(db)], env=env) for _ in range(16)]
    assert all(process.wait(timeout=10) == 0 for process in processes)
    assert JobStore(db).list() == []
