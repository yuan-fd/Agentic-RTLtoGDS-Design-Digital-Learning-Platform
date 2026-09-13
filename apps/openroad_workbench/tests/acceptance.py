from __future__ import annotations

"""Acceptance harness for the workbench terminal core.

Runs the real daemon in-process against the real host shell and asserts the
WORKBENCH_SPEC.md terminal criteria:

1. arbitrary shell commands run through the TUI path with live output
2. cd / environment variables / pipes / redirection / long tasks / Ctrl-C
3. openroad, tclsh, python and make run in the same terminal context
4. no fabricated state: every claimed pass comes from a recorded run

Usage::

    PYTHONPATH=<repo>/apps python3 -m openroad_workbench.tests.acceptance
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.request
from typing import Any, Dict, List, Optional

from ..backend import config as config_mod
from ..backend.core import Workbench
from ..backend.server import Server

TEST_PORT = int(os.environ.get("OWB_TEST_PORT", "8799"))


class Watcher:
    """Deterministic event waiter (no replay, so ordering is unambiguous)."""

    def __init__(self, bus) -> None:
        self.bus = bus
        self.queue = bus.subscribe(replay=False)

    async def wait(self, type_: str, timeout: float = 40.0, **match: Any) -> Optional[Dict[str, Any]]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                event = await asyncio.wait_for(self.queue.get(), timeout=max(0.1, deadline - time.time()))
            except asyncio.TimeoutError:
                return None
            if event.get("type") != type_:
                continue
            data = event.get("data") or {}
            if all(data.get(key) == value or (data.get(key) or {}).get(key) == value for key, value in match.items()):
                return event
        return None

    def drain(self) -> None:
        while not self.queue.empty():
            self.queue.get_nowait()


class Report:
    def __init__(self) -> None:
        self.rows: List[Any] = []

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.rows.append((name, ok, detail))
        print("  %s %s%s" % ("PASS" if ok else "FAIL", name, ("  -- %s" % detail) if detail else ""), flush=True)
        return ok

    @property
    def failed(self) -> int:
        return sum(1 for _, ok, _ in self.rows if not ok)


async def run_command(
    workbench: Workbench,
    watcher: Watcher,
    session_id: str,
    command: str,
    timeout: float = 60.0,
) -> Optional[Dict[str, Any]]:
    """Type a command into the session exactly like a client would."""
    watcher.drain()
    workbench.write_input(session_id, command + "\r")
    event = await watcher.wait("run.completed", timeout=timeout)
    return (event or {}).get("data", {}).get("run")


async def wait_for_prompt(watcher: Watcher, workbench: Workbench, session_id: str, timeout: float = 60.0) -> bool:
    """Wait for an interactive prompt.

    Polls the screen as well as the event queue: the first prompt can be emitted
    before this test subscribes (the daemon warms the MCP catalog during
    ``Workbench.start``), so event-only waiting is racy by construction.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        screen = "\n".join(workbench.screen(session_id, lines=40)["screen"])
        if "$" in screen or "#" in screen:
            return True
        try:
            await asyncio.wait_for(watcher.queue.get(), timeout=0.5)
        except asyncio.TimeoutError:
            pass
    return False


def http_elapsed(path: str, timeout: float = 20.0) -> float:
    url = "http://127.0.0.1:%d%s" % (TEST_PORT, path)
    start = time.time()
    with urllib.request.urlopen(url, timeout=timeout) as response:
        response.read()
    return time.time() - start


def http_expect_error(path: str, method: str, payload: dict):
    url = "http://127.0.0.1:%d%s" % (TEST_PORT, path)
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method=method,
        headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def _make_fake_orfs_tree(root: str) -> None:
    """A miniature ORFS result tree, so the indexer is tested on real shapes
    instead of on an empty directory."""
    files = [
        "config.mk",
        "constraint.sdc",
        "reports/congestion.rpt",
        "metrics.json",
        "results/sky130hd/gcd/base/3_place/congestion.webp",
        "logs/sky130hd/gcd/base/1_synth/synth.log",
        "scripts/flow.tcl",
    ]
    for rel in files:
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("x\n")


async def forged_osc_check(workbench: "Workbench", watcher: Watcher, session_id: str) -> bool:
    """A program printing the workbench's private OSC sequence must not be able
    to invent a Run: the sequence carries a per-session token."""
    watcher.drain()
    token_before = workbench.get_session(session_id).osc_token
    payload = (
        '{"t":"prompt","ec":0,"cwd":"/etc","cmd":"FORGED-MUST-NOT-APPEAR"}'
    )
    # printf with a literal ESC; the whole thing is single-quoted for the shell.
    forged = "printf '\\033]7770;owb;" + payload + "\\007'\r"
    workbench.write_input(session_id, forged)
    await watcher.wait("run.completed", timeout=25)
    await asyncio.sleep(0.8)
    runs = workbench.list_runs(session_id=session_id, limit=20)
    forged_seen = any((r.get("command") or "").strip() == "FORGED-MUST-NOT-APPEAR" for r in runs)
    cwd_now = (workbench.get_session(session_id).cwd or "").rstrip("/")
    return (not forged_seen) and cwd_now != "/etc" and bool(token_before)


def http_headers(path: str, timeout: float = 8.0):
    """Headers only: the SSE endpoint never ends its body on purpose."""
    url = "http://127.0.0.1:%d%s" % (TEST_PORT, path)
    response = urllib.request.urlopen(url, timeout=timeout)
    try:
        return response.status, response.headers.get("content-type", "")
    finally:
        response.close()


def http_text(path: str, timeout: float = 20.0) -> str:
    url = "http://127.0.0.1:%d%s" % (TEST_PORT, path)
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


async def http_json_async(path: str, method: str = "GET", payload: Optional[Dict[str, Any]] = None) -> Any:
    return await asyncio.to_thread(http_json, path, method, payload)


def http_json(path: str, method: str = "GET", payload: Optional[Dict[str, Any]] = None) -> Any:
    url = "http://127.0.0.1:%d%s" % (TEST_PORT, path)
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method,
                                     headers={"content-type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


async def main() -> int:
    report = Report()
    workdir = tempfile.mkdtemp(prefix="owb-accept-")
    config = config_mod.load_config()
    config.update({
        "port": TEST_PORT,
        "host": "127.0.0.1",
        "default_cwd": workdir,
        "mcp_repo": config_mod.resolve_mcp_repo() or "",
        "artifact_scan_interval": 3600.0,
    })

    loop = asyncio.get_running_loop()
    workbench = Workbench(loop, config)
    await workbench.start()
    server = Server(workbench, "127.0.0.1", TEST_PORT)
    await server.start()
    watcher = Watcher(workbench.bus)

    try:
        sessions = workbench.list_sessions()
        report.check("daemon creates a main terminal session", len(sessions) == 1 and bool(sessions[0]["alive"]),
                     json.dumps(sessions[0] if sessions else {}, ensure_ascii=False)[:160])
        session_id = sessions[0]["id"]

        ready = await wait_for_prompt(watcher, workbench, session_id)
        report.check("shell is interactive and reaches a prompt", ready)

        # ------------------------------------------------ criterion 2: basics
        run = await run_command(workbench, watcher, session_id, "pwd")
        ok = bool(run) and run.get("exit_code") == 0 and workdir in "\n".join(
            workbench.screen(session_id, lines=40)["screen"])
        report.check("arbitrary command runs and prints to the shared screen", ok,
                     "exit=%s" % (run or {}).get("exit_code"))

        run = await run_command(workbench, watcher, session_id, "cd /tmp && pwd")
        screen = "\n".join(workbench.screen(session_id, lines=40)["screen"])
        report.check("cd changes directory (cwd tracked)", bool(run) and run.get("exit_code") == 0 and "/tmp" in screen,
                     "cwd=%s" % workbench.get_session(session_id).cwd)

        run = await run_command(workbench, watcher, session_id, "export OWB_TEST_VALUE=123 && echo $OWB_TEST_VALUE")
        report.check("environment variables work", bool(run) and "123" in "\n".join(
            workbench.screen(session_id, lines=40)["screen"]))

        run = await run_command(workbench, watcher, session_id, "echo hello | tee owb_pipe.txt")
        piped = os.path.isfile("/tmp/owb_pipe.txt") or os.path.isfile(os.path.join(workdir, "owb_pipe.txt"))
        report.check("pipes and redirection work", bool(run) and piped,
                     "tee file present=%s" % piped)

        run = await run_command(workbench, watcher, session_id, "python3 -c \"print('python works')\"")
        report.check("python3 runs inside the same terminal context",
                     bool(run) and run.get("exit_code") == 0)

        tcl = shutil.which("tclsh")
        if tcl:
            run = await run_command(workbench, watcher, session_id, "tclsh <<< 'puts TCL_OK'")
            report.check("tclsh runs inside the same terminal context",
                         bool(run) and "TCL_OK" in "\n".join(workbench.screen(session_id, lines=40)["screen"]))
        else:
            report.check("tclsh runs inside the same terminal context", False, "tclsh not installed")

        run = await run_command(workbench, watcher, session_id, "make --version | head -1")
        report.check("make runs inside the same terminal context", bool(run) and run.get("exit_code") == 0)

        # -------------------------------------------- criterion 2: long + ^C
        watcher.drain()
        workbench.write_input(session_id, "sleep 30\r")
        started = await watcher.wait("run.started", timeout=20)
        report.check("long-running command is tracked as a live run", bool(started),
                     "command=%s" % ((started or {}).get("data", {}).get("run", {}) or {}).get("command"))
        await asyncio.sleep(1.5)
        workbench.interrupt(session_id)
        completed = await watcher.wait("run.completed", timeout=25)
        run = (completed or {}).get("data", {}).get("run") or {}
        report.check("Ctrl-C interrupts the foreground process",
                     run.get("status") == "cancelled" and run.get("exit_code") == 130,
                     "status=%s exit=%s" % (run.get("status"), run.get("exit_code")))

        run = await run_command(workbench, watcher, session_id, "echo ALIVE_AFTER_CTRLC")
        report.check("shell survives Ctrl-C and keeps working",
                     bool(run) and "ALIVE_AFTER_CTRLC" in "\n".join(workbench.screen(session_id, lines=40)["screen"]))

        # ------------------------------------------------------ openroad check
        openroad = shutil.which("openroad")
        if openroad:
            run = await run_command(workbench, watcher, session_id, "openroad -version", timeout=90)
            report.check("openroad runs inside the same terminal context",
                         bool(run) and run.get("exit_code") == 0, "exit=%s" % (run or {}).get("exit_code"))
        else:
            report.check("openroad runs inside the same terminal context", False, "openroad not on PATH")

        # ------------------------------------------- failures are not masked
        run = await run_command(workbench, watcher, session_id, "false")
        report.check("non-zero exit codes are reported honestly",
                     bool(run) and run.get("exit_code") == 1 and run.get("status") == "failed",
                     "status=%s exit=%s" % ((run or {}).get("status"), (run or {}).get("exit_code")))

        # ---------------------------------------------------------- HTTP API
        status = await http_json_async("/api/status")
        # Assert the *original* contract the task's acceptance command relied on,
        # not just the new fields.
        legacy_ok = (
            status.get("ok") is True
            and status.get("transport") == "stdio"
            and isinstance(status.get("repo"), str) and bool(status.get("repo"))
            and status.get("tool_count") == 15
        )
        report.check("/api/status keeps its original contract (ok/transport/repo/tool_count)",
                     legacy_ok,
                     "ok=%s transport=%s repo=%s tool_count=%s" % (
                         status.get("ok"), status.get("transport"),
                         status.get("repo"), status.get("tool_count")))
        report.check("/api/status does not block on MCP tool calls",
                     (await asyncio.to_thread(http_elapsed, "/api/status")) < 2.0,
                     "%.2fs" % (await asyncio.to_thread(http_elapsed, "/api/status")))

        state = await http_json_async("/api/state")
        report.check("/api/state exposes designs/sessions/runs/artifacts",
                     all(key in state for key in ("designs", "sessions", "runs", "artifacts")))

        runs = (await http_json_async("/api/runs"))["runs"]
        report.check("runs are queryable over HTTP", len(runs) >= 5, "%d runs" % len(runs))

        watcher.drain()
        await http_json_async("/api/sessions/%s/input" % session_id, "POST", {"data": "echo HTTP_INPUT\r"})
        completed = await watcher.wait("run.completed", timeout=30)
        report.check("HTTP clients drive the same PTY as the TUI would",
                     bool(completed) and "HTTP_INPUT" in str((completed or {}).get("data")),
                     "run=%s" % ((completed or {}).get("data", {}).get("run", {}) or {}).get("command"))

        screen_a = workbench.screen(session_id, lines=50)["screen"]
        screen_b = (await http_json_async("/api/sessions/%s/screen?lines=50" % session_id))["screen"]
        report.check("two clients observe the identical screen (shared state)", screen_a == screen_b)

        try:
            tools = (await http_json_async("/api/tools?refresh=1"))["tools"]
            report.check("official MCP catalog is fully exposed (15 tools)", len(tools) == 15,
                         "%d tools: %s" % (len(tools), ", ".join(t["name"] for t in tools[:4])))
        except Exception as exc:
            report.check("official MCP catalog is fully exposed (15 tools)", False, str(exc))

        # ------------------------------- scrollback + colour + ORFS stages
        await run_command(workbench, watcher, session_id, "seq 1 400 >/dev/null; seq 1 400")
        deep = workbench.screen(session_id, lines=5000)
        report.check("terminal keeps scrollback history",
                     deep.get("history_len", 0) > 0 and len(deep.get("screen") or []) > 200,
                     "history_len=%s lines=%s" % (deep.get("history_len"), len(deep.get("screen") or [])))

        await run_command(workbench, watcher, session_id, "printf '\\033[31mRED\\033[0m plain\\n'")
        frame = workbench.screen(session_id, lines=60)
        coloured = any(
            (run.get("fg") or "default") not in ("default",)
            for line in (frame.get("runs") or []) for run in line
        )
        report.check("terminal frame carries ANSI colour", coloured,
                     "runs=%d" % sum(len(line) for line in (frame.get("runs") or [])))

        # Fixture: the stage lines OpenROAD-flow-scripts actually prints
        # (flow/scripts/flow.sh: echo "Running $2.tcl, stage $1").
        orfs_lines = [
            "Running synth_odb.tcl, stage 1_synth",
            "Running floorplan.tcl, stage 2_floorplan",
            "Running macro_place.tcl, stage 2_floorplan",
            "Running tapcell.tcl, stage 2_floorplan",
            "Running pdn.tcl, stage 2_floorplan",
            "Running global_place_skip_io.tcl, stage 3_place",
            "Running global_place.tcl, stage 3_place",
            "Running detail_place.tcl, stage 3_place",
            "Running cts.tcl, stage 4_cts",
            "Running global_route.tcl, stage 5_route",
            "Running detail_route.tcl, stage 5_route",
            "Running final_report.tcl, stage 6_final_report",
        ]
        printer = "printf '%s\\n' " + " ".join("'" + line + "'" for line in orfs_lines)
        run = await run_command(workbench, watcher, session_id, printer)
        stages = set((run or {}).get("stages") or [])
        report.check("real ORFS stage lines are recognised",
                     {"synth", "floorplan", "place", "cts", "route", "finish"} <= stages,
                     "stages=%s" % sorted(stages))

        # ------------------------------------------- artifact index (SC 5 seed)
        _make_fake_orfs_tree(workdir)
        registered = await http_json_async("/api/designs", "POST", {"path": workdir, "name": "accept-design"})
        design_id = registered["design"]["id"]
        await asyncio.to_thread(lambda: time.sleep(0.6))
        await http_json_async("/api/artifacts/refresh", "POST", {"design_id": design_id})
        listing = await http_json_async("/api/artifacts", "GET")
        found = listing["artifacts"]
        kinds = {a["kind"] for a in found}
        report.check("artifact index classifies reports/images/logs/metrics/scripts",
                     {"report", "image", "log", "metric", "script"} <= kinds,
                     "kinds=%s n=%d" % (sorted(kinds), len(found)))
        staged = [a for a in found if a.get("stage") == "place"]
        report.check("artifact index derives the ORFS stage from the path", bool(staged),
                     "place artifacts=%d" % len(staged))

        # ------------------------------------------------- destructive gate
        blocked = await asyncio.to_thread(
            http_expect_error, "/api/tool", "POST",
            {"tool": "run_orfs_stage", "arguments": {"design": "gcd"}})
        report.check("state-changing MCP tools require confirm=true", blocked is not None
                     and blocked[0] == 400 and "confirm" in blocked[1],
                     str(blocked))
        report.check("forged OSC from program output cannot fabricate a run",
                     await forged_osc_check(workbench, watcher, session_id))

        index_html = await asyncio.to_thread(http_text, "/")
        report.check("web dashboard is served", "OpenROAD Workbench" in index_html,
                     "%d bytes" % len(index_html))
        css = await asyncio.to_thread(http_text, "/static/app.css")
        report.check("dashboard stylesheet is served", "--panel" in css, "%d bytes" % len(css))
        js = await asyncio.to_thread(http_text, "/static/app.js")
        report.check("dashboard script is served", "connectTerminal" in js, "%d bytes" % len(js))
        sse_status, sse_type = await asyncio.to_thread(http_headers, "/api/events")
        report.check("SSE event stream opens", sse_status == 200 and "text/event-stream" in sse_type,
                     "%s %s" % (sse_status, sse_type))
    finally:
        await server.stop()
        await workbench.shutdown()
        shutil.rmtree(workdir, ignore_errors=True)

    print("")
    total = len(report.rows)
    print("acceptance: %d/%d checks passed" % (total - report.failed, total))
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
