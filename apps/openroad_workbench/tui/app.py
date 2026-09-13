from __future__ import annotations

"""The Textual application: TUI is the control surface, the daemon owns the truth."""

import asyncio
import json
from typing import Any, Dict, List, Optional

from rich.markup import escape
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from .client import DaemonClient
from .widgets import AgentPane, Sidebar, StatusBar, TerminalPane

HELP = """[b]OpenROAD Workbench[/b]

主终端就是真实 shell：任意命令、管道、重定向、Ctrl-C 都可用。
（Ctrl-C 会发到终端，不会退出本程序）

 Ctrl+N      新建终端          Ctrl+W      关闭当前终端
 Ctrl+1..9   切换终端          Ctrl+B      显示/隐藏侧栏
 Ctrl+J      聚焦 Agent 输入    Esc         回到终端\n Ctrl+E      显示/隐藏 Agent 面板
 Ctrl+G      把 Agent 的代码块填入终端（不执行）
 Ctrl+U/D    向上/向下翻屏      Ctrl+Y      回到最底部
 F1          本帮助            Ctrl+Q      退出（后台任务继续运行）
"""


class WorkbenchTUI(App):
    CSS = """
    Screen { layout: vertical; }
    #topbar { height: 1; background: $boost; color: $text; padding: 0 1; }
    #main { height: 1fr; }
    #status { height: 1; background: $panel; color: $text; padding: 0 1; }
    .section { height: 1; background: $panel; color: $text; padding: 0 1; }
    """
    # Deliberately avoids Ctrl-B/E/J/U/D/Y: those belong to readline and to the
    # shell.  Panel and scroll actions live on F-keys and Alt- combos instead.
    BINDINGS = [
        Binding("ctrl+q", "quit", "退出", priority=True),
        Binding("ctrl+n", "new_session", "新终端"),
        Binding("ctrl+w", "close_session", "关闭终端"),
        Binding("ctrl+g", "send_proposal", "填入终端"),
        Binding("alt+u", "scroll_up", "上翻"),
        Binding("alt+d", "scroll_down", "下翻"),
        Binding("alt+b", "scroll_bottom", "底部"),
        Binding("f1", "help", "帮助"),
        Binding("f2", "focus_agent", "Agent 输入"),
        Binding("f3", "toggle_agent", "Agent 面板"),
        Binding("f4", "toggle_sidebar", "侧栏"),
    ]

    def __init__(self, base_url: str, status: Optional[Dict[str, Any]] = None) -> None:
        super().__init__()
        self.base_url = base_url
        self.initial_status = status or {}
        self.client = DaemonClient(base_url)
        self.state: Dict[str, Any] = {}
        self.active_session: Optional[str] = None
        self._input_queue: asyncio.Queue = asyncio.Queue()
        self._tasks: List[asyncio.Task] = []
        self._ws = None
        self._pty_size = (0, 0)
        self._last_reply = ""
        self._agent_busy = False
        self._refresh_pending = False

    # ------------------------------------------------------------------ layout
    def compose(self) -> ComposeResult:
        yield Static("OpenROAD Workbench", id="topbar")
        with Horizontal(id="main"):
            yield Sidebar(id="sidebar")
            yield TerminalPane(on_input=self.forward_input, on_resize=self.pty_resize, id="terminal")
            yield AgentPane(id="agent")
        yield StatusBar("connecting…", id="status")

    @property
    def pane(self) -> TerminalPane:
        return self.query_one("#terminal", TerminalPane)

    @property
    def sidebar(self) -> Sidebar:
        return self.query_one("#sidebar", Sidebar)

    @property
    def agent(self) -> AgentPane:
        return self.query_one("#agent", AgentPane)

    # ----------------------------------------------------------------- lifecycle
    async def on_mount(self) -> None:
        self.pane.focus()
        self.agent.write_line(HELP)
        self._tasks.append(asyncio.create_task(self._input_pump()))
        self._tasks.append(asyncio.create_task(self._event_loop()))
        await self.refresh_state(initial=True)
        self._tasks.append(asyncio.create_task(self._frame_loop()))

    async def on_unmount(self) -> None:
        for task in self._tasks:
            task.cancel()
        if self._ws is not None:
            await self._ws.close()
        await self.client.close()

    # ------------------------------------------------------------------- state
    async def refresh_state(self, initial: bool = False) -> None:
        try:
            self.state = await self.client.state()
        except Exception as exc:
            self.query_one("#status", StatusBar).update("daemon unreachable: %s" % exc)
            return
        sessions = self.state.get("sessions") or []
        if self.active_session is None or all(s["id"] != self.active_session for s in sessions):
            self.active_session = sessions[0]["id"] if sessions else None
        self.sidebar.update_sessions(sessions, self.active_session)
        runs = await self._safe_runs()
        self.sidebar.update_runs(runs)
        self._refresh_header()
        if initial:
            await self._connect_terminal()

    async def _safe_runs(self) -> List[Dict[str, Any]]:
        try:
            return (self.state.get("runs") or [])[:12]
        except Exception:
            return []

    def _active(self) -> Optional[Dict[str, Any]]:
        for session in self.state.get("sessions") or []:
            if session["id"] == self.active_session:
                return session
        return None

    def _refresh_header(self) -> None:
        if not self.is_mounted or not self.query("#topbar"):
            return
        status = self.state or self.initial_status
        designs = status.get("designs") or []
        design = designs[0] if designs else {}
        session = self._active() or {}
        runs = status.get("runs") or []
        run = runs[0] if runs else {}
        # Every dynamic value is escaped: design names, terminal names, command
        # text, cwd and paths all come from the user and can contain "[".
        bits = [
            "[b]OpenROAD Workbench[/b]",
            "设计 %s" % escape(str(design.get("name") or "-")),
            "终端 %s" % escape(str(session.get("name") or "-")),
            "状态 %s" % escape(str(session.get("status") or "-")),
        ]
        if run and run.get("status") == "running":
            bits.append("运行 %s" % escape(str(run.get("command") or "")[:30]))
            if run.get("stages"):
                bits.append("阶段 %s" % escape(str(run["stages"][-1])))
            bits.append("耗时 %s" % escape(str(run.get("elapsed_text", "-"))))
        self.query_one("#topbar", Static).update("  ·  ".join(bits))

        counts = status.get("artifacts") or {}
        stage = (run.get("stages") or ["-"])[-1] if run else "-"
        running = bool(run) and run.get("status") == "running"
        self.query_one("#status", StatusBar).update(
            "cwd %s   pid %s   %s   %s   stage %s   结果[报告%s 图%s 日志%s]   Ctrl+N 新终端 · Ctrl+J Agent"
            % (
                escape(str(session.get("cwd") or "-")),
                session.get("pid") or "-",
                "RUNNING" if session.get("status") == "running" else "IDLE",
                ("run " + escape(str(run.get("command") or "")[:24])) if running else "空闲",
                escape(str(stage)),
                counts.get("report", 0),
                counts.get("image", 0),
                counts.get("log", 0),
            )
        )

    # --------------------------------------------------------------- terminal
    async def _connect_terminal(self) -> None:
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        if not self.active_session:
            return
        try:
            self._ws = await self.client.terminal_socket(self.active_session, lines=2000)
        except Exception as exc:
            self.agent.write_line("[red]终端连接失败：%s[/red]" % escape(str(exc)))
            return
        self.pane.session_id = self.active_session
        self.pane.focus()

    async def _frame_loop(self) -> None:
        while True:
            if self._ws is None:
                await asyncio.sleep(0.2)
                continue
            try:
                message = await self._ws.receive()
            except Exception:
                self._ws = None
                await asyncio.sleep(0.5)
                continue
            if message.type.name == "CLOSED":
                self._ws = None
                await asyncio.sleep(0.5)
                continue
            if message.type.name != "TEXT":
                continue
            try:
                frame = json.loads(message.data)
            except Exception:
                continue
            if frame.get("type") == "frame":
                self.pane.set_frame(frame)
                self._sync_size_if_needed()

    def _sync_size_if_needed(self) -> None:
        cols = self.pane.size.width - 2
        rows = self.pane.size.height
        if cols < 20 or rows < 5:
            return
        if (cols, rows) != self._pty_size:
            self._pty_size = (cols, rows)
            asyncio.create_task(self._resize(cols, rows))

    async def _resize(self, cols: int, rows: int) -> None:
        if not self.active_session:
            return
        try:
            await self.client.resize(self.active_session, cols, rows)
        except Exception:
            pass

    def pty_resize(self, cols: int, rows: int) -> None:
        adjusted = (max(20, cols - 2), max(5, rows))
        if adjusted != self._pty_size:
            self._pty_size = adjusted
            asyncio.create_task(self._resize(*adjusted))

    def forward_input(self, data: str) -> None:
        self._input_queue.put_nowait(data)

    async def _input_pump(self) -> None:
        while True:
            data = await self._input_queue.get()
            batch = [data]
            while not self._input_queue.empty() and sum(len(x) for x in batch) < 1024:
                batch.append(self._input_queue.get_nowait())
            payload = "".join(batch)
            if not self.active_session:
                continue
            try:
                await self.client.send_input(self.active_session, payload)
            except Exception as exc:
                self.agent.write_line("[red]输入失败：%s[/red]" % escape(str(exc)))

    # ------------------------------------------------------------------ events
    async def _event_loop(self) -> None:
        while True:
            try:
                async for event in self.client.events():
                    if event.get("type") in (
                        "run.started", "run.completed", "session.started", "session.exited",
                        "session.updated", "stage.observed", "terminal.output",
                    ):
                        self._schedule_refresh(event.get("type") == "run.completed")
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(1.0)

    def _schedule_refresh(self, immediate: bool = False) -> None:
        if self._refresh_pending:
            return
        self._refresh_pending = True

        async def run() -> None:
            if not immediate:
                await asyncio.sleep(0.4)
            try:
                await self.refresh_state()
            finally:
                self._refresh_pending = False

        asyncio.create_task(run())

    # ----------------------------------------------------------------- actions
    async def action_new_session(self) -> None:
        try:
            session = await self.client.create_session()
            await self.refresh_state()
            self.active_session = (session.get("session") or {}).get("id") or self.active_session
            await self._connect_terminal()
            self.agent.write_line("新终端：%s" % escape(str((session.get("session") or {}).get("name"))))
        except Exception as exc:
            self.agent.write_line("[red]新建终端失败：%s[/red]" % escape(str(exc)))

    async def action_close_session(self) -> None:
        if not self.active_session:
            return
        try:
            await self.client.close_session(self.active_session)
        except Exception as exc:
            self.agent.write_line("[red]关闭失败：%s[/red]" % escape(str(exc)))
        self.active_session = None
        await self.refresh_state()
        await self._connect_terminal()

    def action_toggle_sidebar(self) -> None:
        sidebar = self.sidebar
        sidebar.display = not sidebar.display

    def action_toggle_agent(self) -> None:
        agent = self.agent
        agent.display = not agent.display
        if not agent.display:
            self.pane.focus()

    def action_focus_agent(self) -> None:
        self.agent.prompt.focus()

    async def action_send_proposal(self) -> None:
        proposal = _first_code_block(self._last_reply)
        if not proposal:
            self.agent.write_line("[yellow]Agent 最近回复里没有可填入的代码块[/yellow]")
            return
        result = await self.client.fill(self.active_session, proposal)
        mode = result.get("mode")
        if mode == "insert":
            self.agent.write_line("[green]已填入终端输入栏，未执行。[/green]确认后按回车执行。")
        elif mode == "bracketed":
            self.agent.write_line(
                "[green]已用括号粘贴填入多行脚本，未执行。[/green]检查无误后按回车执行。")
        elif mode == "refused":
            self.agent.write_line(
                "[yellow]没有自动填入：%s[/yellow] 请手动复制上面的代码块。"
                % escape(str(result.get("reason") or "")))
        self.pane.focus()

    def action_scroll_bottom(self) -> None:
        self.pane.scroll_to_bottom()

    def action_help(self) -> None:
        self.agent.write_line(HELP)

    # key handling: ctrl+1..9 switch terminals, ctrl+u/d scroll
    async def on_key(self, event) -> None:
        key = getattr(event, "key", "") or ""
        if key.startswith("ctrl+") and len(key) == 6 and key[5].isdigit():
            index = int(key[5])
            sessions = self.state.get("sessions") or []
            if 1 <= index <= len(sessions):
                self.active_session = sessions[index - 1]["id"]
                await self._connect_terminal()
                self._refresh_header()
                event.stop()
            return
        if key == "escape" and self.agent.prompt.has_focus:
            self.pane.focus()
            event.stop()

    def action_scroll_up(self) -> None:
        self.pane.scroll_back(6)

    def action_scroll_down(self) -> None:
        self.pane.scroll_back(-6)

    # ------------------------------------------------------------------- agent
    async def on_input_submitted(self, event) -> None:
        if event.input.id != "agent-input":
            return
        question = event.value.strip()
        event.input.value = ""
        if not question or self._agent_busy:
            return
        self._agent_busy = True
        self.agent.write_user("[b cyan]你[/b cyan]  %s" % escape(question))
        collected: List[str] = []
        try:
            async for chunk in self.client.ask(question, session_id=self.active_session):
                if chunk.get("type") == "start":
                    self.agent.write_line("[dim]provider=%s corpus=%s[/dim]" % (
                        chunk.get("provider"), (chunk.get("corpus") or {}).get("records")))
                elif chunk.get("type") == "delta":
                    collected.append(chunk.get("text") or "")
                elif chunk.get("type") == "done":
                    pass
            text = "".join(collected) or "(空回复)"
            self._last_reply = text
            self.agent.write_line("[b green]Agent[/b green]\n%s" % escape(text))
        except Exception as exc:
            self.agent.write_line("[red]Agent 调用失败：%s[/red]" % escape(str(exc)))
        finally:
            self._agent_busy = False
            self.agent.prompt.focus()


def _first_code_block(text: str) -> str:
    """Extract the first fenced code block. Never appends a newline: a trailing
    newline is Enter, and Enter *executes* the text."""
    if not text:
        return ""
    parts = text.split("```")
    if len(parts) < 3:
        return ""
    block = parts[1]
    lines = block.split("\n")
    if lines and lines[0].strip().lower() in (
        "bash", "sh", "shell", "zsh", "tcl", "tclsh", "python", "py", "makefile", "make", ""):
        lines = lines[1:]
    return "\n".join(lines).strip()



def run_tui(base_url: str, status: Optional[Dict[str, Any]] = None) -> int:
    app = WorkbenchTUI(base_url, status)
    app.run()
    return 0
