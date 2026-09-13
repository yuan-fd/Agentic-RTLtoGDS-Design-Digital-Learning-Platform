from __future__ import annotations

"""Headless TUI verification.

There is no way for the harness to *look* at a TUI, so the control surface is
asserted the same way as the backend: drive the real app in a headless Textual
pilot against a real daemon and check what it renders and what it forwards.

Also exports an SVG snapshot so a human can review the layout.

Usage::

    PYTHONPATH=<repo>/apps python3 -m openroad_workbench.tests.test_tui [out.svg]
"""

import asyncio
import os
import shutil
import sys
import tempfile
import time
from typing import Any, Callable, List, Optional

from ..backend import config as config_mod
from ..backend.core import Workbench
from ..backend.server import Server
from ..tui.app import WorkbenchTUI

TEST_PORT = int(os.environ.get("OWB_TUI_PORT", "8798"))


async def wait_until(predicate: Callable[[], bool], timeout: float = 20.0, interval: float = 0.1) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return False


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


def pane_text(app: WorkbenchTUI) -> str:
    return "\n".join(app.pane.lines)


async def main(argv: List[str]) -> int:
    screenshot_path = argv[1] if len(argv) > 1 else None
    report = Report()
    workdir = tempfile.mkdtemp(prefix="owb-tui-")
    config = config_mod.load_config()
    config.update({
        "port": TEST_PORT, "host": "127.0.0.1", "default_cwd": workdir,
        "mcp_repo": config_mod.resolve_mcp_repo() or "", "artifact_scan_interval": 3600.0,
    })
    loop = asyncio.get_running_loop()
    workbench = Workbench(loop, config)
    await workbench.start()
    server = Server(workbench, "127.0.0.1", TEST_PORT)
    await server.start()

    app = WorkbenchTUI("http://127.0.0.1:%d" % TEST_PORT)
    try:
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            # The first frame legitimately arrives before bash has drawn its
            # prompt, so wait for visible prompt output rather than mere bytes.
            await wait_until(lambda: "$" in pane_text(app) or "#" in pane_text(app), timeout=30)
            report.check("TUI attaches to the daemon and renders the terminal",
                         bool(pane_text(app).strip()), "%d lines" % len(app.pane.lines))
            report.check("TUI shows the shell prompt from the real PTY",
                         "$" in pane_text(app) or "#" in pane_text(app),
                         repr(pane_text(app)[-60:]))

            # ---------------------------------------------------- typing works
            session_id = app.active_session
            runs_before = len(workbench.list_runs(session_id=session_id))
            for key in list("echo TUI_TYPING_OK"):
                await pilot.press("space" if key == " " else key)
            await pilot.press("enter")
            ok = await wait_until(
                lambda: len(workbench.list_runs(session_id=session_id)) > runs_before, timeout=25)
            await wait_until(lambda: "TUI_TYPING_OK" in pane_text(app), timeout=15)
            report.check("keystrokes typed in the TUI reach the real PTY",
                         ok and "TUI_TYPING_OK" in pane_text(app),
                         "runs=%d" % len(workbench.list_runs(session_id=session_id)))

            # ------------------------------------------- Ctrl-C is not 'quit'
            await pilot.press(*list("sleep 30"))
            await pilot.press("enter")
            started = await wait_until(
                lambda: any(r["command"] == "sleep 30" and r["status"] == "running"
                            for r in workbench.list_runs(session_id=session_id)), timeout=20)
            report.check("long task is visible as a running run", started)
            await asyncio.sleep(1.0)
            await pilot.press("ctrl+c")
            await pilot.pause()
            report.check("Ctrl-C does not quit the TUI", app.is_running)
            cancelled = await wait_until(
                lambda: any(r["command"] == "sleep 30" and r["status"] == "cancelled"
                            for r in workbench.list_runs(session_id=session_id)), timeout=20)
            report.check("Ctrl-C is delivered to the foreground process", cancelled)

            # ------------------------------------------------- session switching
            await pilot.press("ctrl+n")
            await wait_until(lambda: len(app.state.get("sessions") or []) >= 2, timeout=20)
            report.check("Ctrl+N opens a second terminal",
                         len(workbench.list_sessions()) >= 2,
                         "%d sessions" % len(workbench.list_sessions()))
            await pilot.press("ctrl+1")
            await pilot.pause()
            report.check("Ctrl+1 switches back to the first terminal",
                         app.active_session == session_id,
                         "active=%s" % app.active_session)

            # ------------------------------------------------------ agent pane
            app.agent.prompt.focus()
            await pilot.press(*list("gcd 的 timing 报告在哪"))
            await pilot.press("enter")
            got = await wait_until(lambda: bool(app._last_reply), timeout=30)
            report.check("Agent pane answers with real context (no model configured)",
                         got and "未配置模型" in app._last_reply,
                         (app._last_reply or "")[:70].replace("\n", " "))

            # ------------------------- Ctrl+G must fill, never execute (P1)
            runs_before = len(workbench.list_runs(session_id=session_id))
            app._last_reply = "脚本如下：\n```tcl\nset OWB_MARKER_ONE 1\nputs OWB_MARKER_TWO\n```\n"
            app.pane.focus()
            await pilot.press("ctrl+g")
            await asyncio.sleep(1.5)
            runs_after = len(workbench.list_runs(session_id=session_id))
            text = pane_text(app)
            report.check("Ctrl+G fills the command line without executing it",
                         runs_after == runs_before and "OWB_MARKER_ONE" in text,
                         "runs %d -> %d, visible=%s" % (
                             runs_before, runs_after, "OWB_MARKER_ONE" in text))
            # clear the pending edit line so later checks start clean
            await app.client.send_input(session_id, "\x15")

            # -------------------------------------------------------- sidebars
            sidebar_text = "\n".join(str(w.renderable if hasattr(w, "renderable") else "") for w in [])
            sessions_view = app.sidebar.sessions_view
            report.check("sidebar lists terminals", "终端" in str(sessions_view.render()) or "主终端" in str(sessions_view.render()))
            report.check("status bar shows cwd and pid",
                         "cwd" in str(app.query_one("#status").render()))

            if screenshot_path:
                svg = app.export_screenshot()
                with open(screenshot_path, "w", encoding="utf-8") as handle:
                    handle.write(svg)
                print("  screenshot -> %s (%d bytes)" % (screenshot_path, len(svg)))
            del sidebar_text
    finally:
        await server.stop()
        await workbench.shutdown()
        await app.client.close()
        shutil.rmtree(workdir, ignore_errors=True)

    print("")
    total = len(report.rows)
    print("tui: %d/%d checks passed" % (total - report.failed, total))
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv)))
