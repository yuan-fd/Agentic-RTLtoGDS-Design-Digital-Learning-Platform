"""The curses-independent terminal controller projects a live API cursor."""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from apps.l1_workbench.terminal_dashboard import Client, Dashboard


ROOT = Path(__file__).parents[1]
ENV = {**os.environ, "PYTHONPATH": ":".join(str(ROOT / item) for item in
       ("packages/contracts/src", "packages/scheduler/src", "packages/execution/src", "."))}


def _port():
    sock = socket.socket(); sock.bind(("127.0.0.1", 0))
    result = sock.getsockname()[1]; sock.close()
    return result


def test_terminal_controller_submits_async_and_replays_only_cursor_events(tmp_path):
    port = _port()
    server = subprocess.Popen([sys.executable, "apps/l1_workbench/server.py",
        "--state-root", str(tmp_path), "--port", str(port)], cwd=ROOT, env=ENV)
    dashboard = Dashboard(Client(f"http://127.0.0.1:{port}"))
    try:
        for _ in range(100):
            try:
                dashboard.client.get("/api/l1/sessions/missing/events")
            except Exception:
                if server.poll() is None:
                    time.sleep(.03)
                    continue
                raise
        dashboard.command(":new Run one bounded implementation flow.")
        dashboard.command(":answer objective-1 one audited run")
        dashboard.command(":baseline")
        for _ in range(100):
            dashboard.refresh()
            if any(event["kind"] == "state_transition" for event in dashboard.events):
                break
            time.sleep(.05)
        assert any(event["kind"] == "goal_finalized" for event in dashboard.events)
        assert any(event["kind"] == "tool_receipt" for event in dashboard.events)
        assert any(event["kind"] == "state_transition" for event in dashboard.events)
        state_rows = "\n".join(dashboard._state_rows())
        assert "Runtime, not this client" not in state_rows
        assert "l1_tool_runs" in str(dashboard.events)
        first_count, first_cursor = len(dashboard.events), dashboard.after
        dashboard.refresh()
        assert len(dashboard.events) == first_count and dashboard.after == first_cursor
        dashboard.command(":recover")
        assert "no duplicate Runtime submission" in dashboard.notice
    finally:
        server.terminate(); server.wait(timeout=5)
