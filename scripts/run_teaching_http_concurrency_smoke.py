#!/usr/bin/env python3
"""Bounded HTTP concurrency smoke for the teaching Session surface."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["OPENROAD_PLATFORM_NO_AUTH"] = "1"

from apps.api.app import ApiState, build_server  # noqa: E402


def post(base: str, path: str, payload: dict) -> dict:
    request = urllib.request.Request(
        f"{base}{path}", data=json.dumps(payload).encode(),
        method="POST", headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())


def get(base: str, session_id: str) -> dict:
    with urllib.request.urlopen(
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
            with ThreadPoolExecutor(max_workers=8) as pool:
                created = list(pool.map(
                    lambda i: post(base, "/api/teaching/sessions", {"text": f"concurrency smoke {i}", "teaching_mode": "guided"}),
                    range(8),
                ))
                ids = [item["session"]["session_id"] for item in created]
                def prepare(sid: str, item: dict) -> dict:
                    questions = (item.get("draft") or {}).get("questions") or []
                    answers = [{"question_id": q["question_id"], "field": q["field"],
                                "value": "bounded concurrency smoke"} for q in questions]
                    return post(base, f"/api/teaching/sessions/{sid}/answers", {"answers": answers})
                prepared = list(pool.map(lambda pair: prepare(pair[0], pair[1]), zip(ids, created)))
                list(pool.map(lambda sid: post(
                    base, f"/api/teaching/sessions/{sid}/execute",
                    {"decision_summary": "bounded concurrency smoke"}), ids))
                snapshots = list(pool.map(lambda sid: get(base, sid), ids))
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)
    if (len(set(ids)) != 8 or
            any((item.get("session") or {}).get("session_id") not in ids for item in snapshots)):
        raise RuntimeError("teaching HTTP concurrency smoke returned inconsistent sessions")
    print(json.dumps({"accepted": True, "concurrent_sessions": 8,
                      "snapshot_reads": len(snapshots),
                      "execute_responses": len(prepared)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
