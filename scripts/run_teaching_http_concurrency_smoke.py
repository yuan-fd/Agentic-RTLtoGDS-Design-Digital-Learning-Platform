#!/usr/bin/env python3
"""Bounded HTTP concurrency smoke for the teaching Session surface."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import urllib.request
import http.cookiejar
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps.api.app import ApiState, build_server  # noqa: E402


def post(opener, base: str, path: str, payload: dict, *, client_ip: str | None = None) -> dict:
    request = urllib.request.Request(
        f"{base}{path}", data=json.dumps(payload).encode(),
        method="POST", headers={"Content-Type": "application/json",
                                 **({"X-Forwarded-For": client_ip} if client_ip else {})},
    )
    with opener.open(request, timeout=10) as response:
        return json.loads(response.read())


def get(opener, base: str, session_id: str) -> dict:
    with opener.open(
        f"{base}/api/teaching/sessions/{session_id}", timeout=10
    ) as response:
        return json.loads(response.read())


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="teaching-http-concurrency-") as raw:
        root = Path(raw)
        state = ApiState(
            root / "platform.db", root / "uploads", root / "orfs",
            design_root=root / "designs", legacy_root=root / "legacy",
            runtime_db_path=root / "runtime.sqlite", auth_db_path=root / "auth.db",
            workbench_config={"root": root / "workbench", "backend": "smoke"},
            load_taiwei_plugin=False,
        )
        server = build_server("127.0.0.1", 0, state)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            openers = []
            for i in range(8):
                jar = http.cookiejar.CookieJar()
                opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
                post(opener, base, "/api/auth/register", {
                    "username": f"concurrency_user_{i}", "password": "StrongSmokePassword-2026!",
                }, client_ip=f"192.0.2.{i + 1}")
                openers.append(opener)
            with ThreadPoolExecutor(max_workers=8) as pool:
                created = list(pool.map(
                    lambda pair: post(pair[1], base, "/api/teaching/sessions", {"text": f"concurrency smoke {pair[0]}", "teaching_mode": "guided"}),
                    enumerate(openers),
                ))
                ids = [item["session"]["session_id"] for item in created]
                def prepare(sid: str, item: dict) -> dict:
                    questions = (item.get("draft") or {}).get("questions") or []
                    answers = [{"question_id": q["question_id"], "field": q["field"],
                                "value": "bounded concurrency smoke"} for q in questions]
                    return post(openers[ids.index(sid)], base, f"/api/teaching/sessions/{sid}/answers", {"answers": answers})
                prepared = list(pool.map(lambda pair: prepare(pair[0], pair[1]), zip(ids, created)))
                list(pool.map(lambda sid: post(
                    openers[ids.index(sid)], base, f"/api/teaching/sessions/{sid}/execute",
                    {"decision_summary": "bounded concurrency smoke"}), ids))
                snapshots = list(pool.map(lambda sid: get(openers[ids.index(sid)], base, sid), ids))
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and any(
                (item.get("state") or {}).get("status") not in {"observed", "failed"}
                for item in snapshots
            ):
                time.sleep(0.2)
                snapshots = [get(openers[ids.index(sid)], base, sid) for sid in ids]
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)
    if (len(set(ids)) != 8 or
            any((item.get("session") or {}).get("session_id") not in ids for item in snapshots)):
        raise RuntimeError("teaching HTTP concurrency smoke returned inconsistent sessions")
    observed = sum((item.get("state") or {}).get("status") == "observed" for item in snapshots)
    if observed != 8:
        raise RuntimeError(f"teaching HTTP concurrency smoke did not observe all runs: {observed}/8")
    print(json.dumps({"accepted": True, "concurrent_sessions": 8,
                      "snapshot_reads": len(snapshots), "observed_runs": observed,
                      "execute_responses": len(prepared)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
