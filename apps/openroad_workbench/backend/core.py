from __future__ import annotations

"""The workbench state machine.

One instance owns every live object.  The TUI and the Web dashboard are both
*clients* of this object through the HTTP/WebSocket API, so there is no way for
the two surfaces to disagree about what is running.

Threading contract
------------------
PTY reader threads never touch this object directly; they call a callback that
hops onto the event loop.  Everything below therefore runs on the loop thread,
except the artifact scanner which is dispatched with ``asyncio.to_thread`` and
returns plain data.
"""

import asyncio
import json
import os
import signal
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

from . import artifacts as artifacts_mod
from . import config as config_mod
from .events import EventBus
from .mcp_client import MCPClient, MCPError
from .models import Artifact, Conversation, Design, Run, STAGE_ORDER, duration
from .pty_session import PtySession, shell_integration_bashrc, shell_integration_zshrc


class Workbench:
    def __init__(self, loop: asyncio.AbstractEventLoop, config: Optional[Dict[str, Any]] = None) -> None:
        self.loop = loop
        self.config = config or config_mod.load_config()
        self.bus = EventBus(loop)
        mcp_repo = self.config.get("mcp_repo") or config_mod.resolve_mcp_repo() or ""
        self.mcp = MCPClient(mcp_repo) if mcp_repo else MCPClient("/nonexistent")
        self.started_at = time.time()

        self._sessions: Dict[str, PtySession] = {}
        self._meta: Dict[str, Dict[str, Any]] = {}
        self._designs: Dict[str, Design] = {}
        self._design_by_path: Dict[str, str] = {}
        self._runs: Dict[str, Run] = {}
        self._run_seq: List[str] = []
        self._artifacts: Dict[str, List[Artifact]] = {}
        self._conversations: Dict[str, Conversation] = {}
        self._counters: Dict[str, int] = defaultdict(int)
        self._tasks: List[asyncio.Task] = []
        self._background: set = set()
        self._osc_seen: Dict[str, bool] = {}
        self.last_refresh: Dict[str, float] = {}

    # ------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        config_mod.ensure_dirs()
        shell_integration_bashrc(os.path.join(config_mod.SHELL_DIR, "owb.bashrc"))
        shell_integration_zshrc(os.path.join(config_mod.SHELL_DIR, "owb.zshrc"))
        self._tasks.append(asyncio.ensure_future(self._artifact_loop()))
        default_cwd = self.config.get("default_cwd") or os.path.expanduser("~")
        if artifacts_mod.looks_like_design(default_cwd):
            self.register_design(default_cwd)
        if not self._sessions and not self.config.get("_skip_main_session"):
            self.create_session(name="主终端", cwd=default_cwd)
        # Warm the MCP catalog here rather than in the daemon: every embedding
        # (daemon, tests, future front-ends) then gets the same guarantee that
        # /api/status can report the tool count without taking the tool lock.
        if self.mcp.available:
            try:
                await asyncio.wait_for(self.mcp.catalog(), timeout=30)
            except Exception as exc:
                self.bus.publish("mcp.unavailable", error=str(exc))
        self.bus.publish("workbench.ready", pid=os.getpid())

    def spawn(self, coro: Any) -> asyncio.Task:
        """Track fire-and-forget work so shutdown can cancel it and failures are
        visible instead of being dropped on the floor."""
        task = asyncio.ensure_future(coro)
        self._background.add(task)

        def _done(finished: asyncio.Task) -> None:
            self._background.discard(finished)
            if finished.cancelled():
                return
            exc = finished.exception()
            if exc is not None:
                self.bus.publish("task.failed", error="%s: %s" % (type(exc).__name__, exc))

        task.add_done_callback(_done)
        return task

    async def shutdown(self) -> None:
        for task in list(self._tasks) + list(self._background):
            task.cancel()
        for session in list(self._sessions.values()):
            session.terminate(signal.SIGTERM)
        await asyncio.sleep(0.1)
        for session in list(self._sessions.values()):
            session.close()
        await self.mcp.close()
        self.bus.close()

    # -------------------------------------------------------------- sessions
    def _next_id(self, prefix: str) -> str:
        self._counters[prefix] += 1
        return "%s-%d" % (prefix, self._counters[prefix])

    def create_session(
        self,
        name: Optional[str] = None,
        cwd: Optional[str] = None,
        argv: Optional[List[str]] = None,
        design_id: Optional[str] = None,
        cols: int = 120,
        rows: int = 32,
        kind: str = "shell",
    ) -> Dict[str, Any]:
        session_id = self._next_id("term")
        label = name or ("终端 %d" % self._counters["term"])
        workdir = os.path.abspath(os.path.expanduser(cwd or self.config.get("default_cwd") or "~"))
        if not os.path.isdir(workdir):
            workdir = os.path.expanduser("~")
        session = PtySession(
            session_id=session_id,
            name=label,
            cwd=workdir,
            argv=argv,
            cols=cols,
            rows=rows,
            kind=kind,
            design_id=design_id,
            on_event=self._pty_event,
        )
        self._sessions[session_id] = session
        self._meta[session_id] = {
            "design_id": design_id,
            "current_run_id": None,
            "provisional_run_id": None,
        }
        self._osc_seen[session_id] = False
        return session.snapshot()

    def get_session(self, session_id: str) -> Optional[PtySession]:
        return self._sessions.get(session_id)

    def list_sessions(self) -> List[Dict[str, Any]]:
        return [self._session_view(s) for s in self._sessions.values()]

    def _session_view(self, session: PtySession) -> Dict[str, Any]:
        meta = self._meta.get(session.id, {})
        data = session.snapshot(include_screen=False)
        data["design_id"] = meta.get("design_id") or session.design_id
        data["current_run_id"] = meta.get("current_run_id")
        run = self._runs.get(meta.get("current_run_id") or "")
        data["current_command"] = run.command if run else None
        data["stage"] = run.stages[-1] if run and run.stages else None
        data["status"] = "running" if (session.alive and run) else ("idle" if session.alive else "exited")
        return data

    def write_input(self, session_id: str, data: str) -> Dict[str, Any]:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError("unknown session %s" % session_id)
        session.write(data)
        return {"ok": True, "bytes": len(data)}

    def fill_command_line(self, session_id: str, text: str) -> Dict[str, Any]:
        """Insert text into the command line WITHOUT executing it.

        The safety decision lives here, not in the UI: a newline in a PTY means
        Enter, so multi-line text is only ever inserted inside bracketed-paste
        markers, and only when the session guarantees readline understands them.
        """
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError("unknown session %s" % session_id)
        body = (text or "").strip("\n")
        if not body:
            return {"ok": False, "mode": "empty", "inserted": ""}
        if "\n" not in body:
            session.write_raw(body)
            return {"ok": True, "mode": "insert", "inserted": body}
        if not getattr(session, "bracketed_paste", False):
            return {
                "ok": False,
                "mode": "refused",
                "inserted": "",
                "reason": "该终端未启用括号粘贴，自动插入多行会被逐行执行",
            }
        session.write_raw("\x1b[200~" + body + "\x1b[201~")
        return {"ok": True, "mode": "bracketed", "inserted": body}

    def interrupt(self, session_id: str) -> Dict[str, Any]:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError("unknown session %s" % session_id)
        session.interrupt()
        self.bus.publish("session.interrupt", session_id=session_id)
        return {"ok": True}

    def terminate(self, session_id: str) -> Dict[str, Any]:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError("unknown session %s" % session_id)
        session.terminate()
        return {"ok": True}

    def close_session(self, session_id: str) -> Dict[str, Any]:
        session = self._sessions.pop(session_id, None)
        if session is None:
            raise KeyError("unknown session %s" % session_id)
        session.close()
        self.bus.publish("session.closed", session_id=session_id)
        return {"ok": True}

    def rename_session(self, session_id: str, name: str) -> Dict[str, Any]:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError("unknown session %s" % session_id)
        session.name = name.strip() or session.name
        self.bus.publish("session.updated", session=self._session_view(session))
        return self._session_view(session)

    def resize(self, session_id: str, cols: int, rows: int) -> Dict[str, Any]:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError("unknown session %s" % session_id)
        session.resize(cols, rows)
        return {"ok": True, "cols": session.cols, "rows": session.rows}

    def screen(self, session_id: str, lines: int = 200, history: bool = True) -> Dict[str, Any]:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError("unknown session %s" % session_id)
        if history:
            state = session.screen_state(limit=lines)
        else:
            state = {
                "screen": session.screen_lines(limit=lines, include_history=False),
                "history_len": 0,
                "cursor": {"x": session._screen.cursor.x, "y": session._screen.cursor.y},
                "cols": session.cols,
                "rows": session.rows,
            }
        state.update({
            "id": session.id,
            "name": session.name,
            "alive": session.alive,
            "version": session.version,
            "cwd": session.cwd,
            "pid": session.pid,
        })
        return state

    def raw_log(self, session_id: str) -> str:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError("unknown session %s" % session_id)
        return session.raw_text()

    # ------------------------------------------------------------------ events
    def _pty_event(self, type_: str, **data: Any) -> None:
        """Called from PTY reader threads."""
        try:
            self.loop.call_soon_threadsafe(self._apply_pty_event, type_, data)
        except RuntimeError:
            pass

    def _apply_pty_event(self, type_: str, data: Dict[str, Any]) -> None:
        session_id = data.get("session_id")
        if type_ == "terminal.output":
            self.bus.publish(
                "terminal.output",
                session_id=session_id,
                bytes=data.get("bytes", 0),
                text=(data.get("text") or "")[-2000:],
            )
            return
        if type_ == "session.started":
            self.bus.publish("session.started", session=self._session_view(self._sessions[session_id]))
            return
        if type_ == "session.exited":
            self._finish_run_for_session(session_id, exit_code=data.get("exit_code"), reason="exited")
            self.bus.publish(
                "session.exited",
                session_id=session_id,
                exit_code=data.get("exit_code"),
                session=self._session_view(self._sessions[session_id]) if session_id in self._sessions else None,
            )
            return
        if type_ == "command.submitted":
            self._on_command_submitted(session_id, data.get("command") or "")
            return
        if type_ == "shell.prompt":
            self._on_shell_prompt(session_id, data)
            return
        if type_ == "stage.observed":
            self._on_stage(session_id, data.get("stage"))

    # -------------------------------------------------------------------- runs
    def _on_command_submitted(self, session_id: str, command: str) -> None:
        meta = self._meta.get(session_id)
        session = self._sessions.get(session_id)
        if meta is None or session is None or not command.strip():
            return
        if not self._osc_seen.get(session_id):
            # No shell integration: the previous provisional run can only be
            # closed here.  Marked unknown rather than guessed.
            self._finish_run_for_session(session_id, exit_code=None, reason="superseded")
        if meta.get("current_run_id"):
            return
        # Startup rc noise (window-title helpers, module loads) must not become
        # a "run": wait for the first real prompt, with a timeout fallback for
        # shells where integration is unavailable.
        ready = self._osc_seen.get(session_id) or (time.time() - session.started_at) > 3.0
        if not ready:
            return
        run = self._start_run(session_id, command, provisional=True)
        meta["current_run_id"] = run.id

    def _on_shell_prompt(self, session_id: str, data: Dict[str, Any]) -> None:
        self._osc_seen[session_id] = True
        cwd = data.get("cwd")
        command = (data.get("command") or "").strip()
        exit_code = data.get("exit_code")
        meta = self._meta.get(session_id)
        session = self._sessions.get(session_id)
        if meta is None or session is None:
            return
        run_id = meta.get("current_run_id")
        if run_id:
            run = self._runs.get(run_id)
            if run is not None:
                if command:
                    run.command = command
                    run.provisional = False
                self._finish_run(run, exit_code=exit_code)
            meta["current_run_id"] = None
        if cwd:
            session.cwd_hint = cwd
            design_id = self._design_for_cwd(cwd, register=True)
            if design_id:
                meta["design_id"] = design_id
                session.design_id = design_id
        self.bus.publish("session.updated", session=self._session_view(session))

    def _on_stage(self, session_id: str, stage: Optional[str]) -> None:
        if not stage or stage not in STAGE_ORDER:
            return
        meta = self._meta.get(session_id) or {}
        run = self._runs.get(meta.get("current_run_id") or "")
        if run is None or run.stages[-1:] == [stage]:
            return
        if stage not in run.stages:
            run.stages.append(stage)
        self.bus.publish("stage.observed", run_id=run.id, session_id=session_id, stage=stage, run=run.as_dict())

    def _start_run(self, session_id: str, command: str, provisional: bool = True) -> Run:
        session = self._sessions[session_id]
        run_id = self._next_id("run")
        meta = self._meta.get(session_id) or {}
        run = Run(
            id=run_id,
            session_id=session_id,
            design_id=meta.get("design_id") or session.design_id,
            command=command,
            cwd=session.cwd,
            provisional=provisional,
        )
        self._runs[run_id] = run
        self._run_seq.append(run_id)
        self.bus.publish("run.started", run=run.as_dict())
        return run

    def _finish_run(self, run: Run, exit_code: Optional[int]) -> None:
        if run.finished_at is not None:
            return
        run.finished_at = time.time()
        run.exit_code = exit_code
        run.provisional = False
        if exit_code is None:
            run.status = "unknown"
        elif exit_code == 0:
            run.status = "success"
        elif exit_code in (130, 131, 143, -signal.SIGINT, -signal.SIGTERM):
            run.status = "cancelled"
        else:
            run.status = "failed"
        self._persist_run(run)
        self.bus.publish("run.completed", run=run.as_dict())
        if run.design_id:
            self.spawn(self.refresh_artifacts(run.design_id))

    def _finish_run_for_session(self, session_id: str, exit_code: Optional[int], reason: str) -> None:
        meta = self._meta.get(session_id) or {}
        run = self._runs.get(meta.get("current_run_id") or "")
        if run is not None:
            self._finish_run(run, exit_code=exit_code)
        meta["current_run_id"] = None

    def list_runs(self, session_id: Optional[str] = None, design_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        items = [self._runs[rid] for rid in self._run_seq if rid in self._runs]
        if session_id:
            items = [r for r in items if r.session_id == session_id]
        if design_id:
            items = [r for r in items if r.design_id == design_id]
        return [run.as_dict() for run in items[-limit:]][::-1]

    def get_run(self, run_id: str) -> Optional[Run]:
        return self._runs.get(run_id)

    def cancel_run(self, run_id: str) -> Dict[str, Any]:
        run = self._runs.get(run_id)
        if run is None:
            raise KeyError("unknown run %s" % run_id)
        session = self._sessions.get(run.session_id)
        if session is not None and run.finished_at is None:
            session.interrupt()
        return {"ok": True}

    def _persist_run(self, run: Run) -> None:
        try:
            config_mod.ensure_dirs()
            with open(config_mod.runtime_file("runs.jsonl"), "a", encoding="utf-8") as handle:
                handle.write(json.dumps(run.as_dict(), ensure_ascii=False) + "\n")
        except Exception:
            pass

    # ----------------------------------------------------------------- designs
    def register_design(self, path: str, name: Optional[str] = None) -> Design:
        real = os.path.realpath(os.path.abspath(os.path.expanduser(path)))
        existing = self._design_by_path.get(real)
        if existing:
            return self._designs[existing]
        design = Design(
            id=self._next_id("design"),
            name=name or os.path.basename(real.rstrip(os.sep)) or real,
            path=real,
        )
        self._designs[design.id] = design
        self._design_by_path[real] = design.id
        self.bus.publish("design.registered", design=design.as_dict())
        self.spawn(self.refresh_artifacts(design.id))
        return design

    def list_designs(self) -> List[Dict[str, Any]]:
        return [design.as_dict() for design in self._designs.values()]

    def get_design(self, design_id: str) -> Optional[Design]:
        return self._designs.get(design_id)

    def _design_for_cwd(self, cwd: str, register: bool = False) -> Optional[str]:
        path = os.path.realpath(cwd)
        while True:
            if path in self._design_by_path:
                return self._design_by_path[path]
            parent = os.path.dirname(path)
            if parent == path:
                break
            path = parent
        if register and artifacts_mod.looks_like_design(cwd):
            return self.register_design(cwd).id
        return None

    # --------------------------------------------------------------- artifacts
    async def refresh_artifacts(self, design_id: Optional[str] = None) -> Dict[str, Any]:
        targets = [design_id] if design_id else list(self._designs.keys())
        counts: Dict[str, int] = {}
        for target in targets:
            design = self._designs.get(target)
            if design is None:
                continue
            found = await asyncio.to_thread(artifacts_mod.scan_design, design.id, design.path)
            self._artifacts[design.id] = found
            self.last_refresh[design.id] = time.time()
            counts[design.id] = len(found)
        if targets:
            self.bus.publish("artifacts.updated", design_ids=targets, counts=counts)
        return counts

    async def _artifact_loop(self) -> None:
        interval = float(self.config.get("artifact_scan_interval") or 10.0)
        while True:
            try:
                await asyncio.sleep(interval)
                active = {
                    self._meta.get(sid, {}).get("design_id")
                    for sid in self._sessions
                    if self._meta.get(sid, {}).get("current_run_id")
                }
                for design_id in filter(None, active):
                    await self.refresh_artifacts(design_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(interval)

    def list_artifacts(
        self,
        design_id: Optional[str] = None,
        kind: Optional[str] = None,
        stage: Optional[str] = None,
        limit: int = 400,
    ) -> List[Dict[str, Any]]:
        items: List[Artifact] = []
        for key, values in self._artifacts.items():
            if design_id and key != design_id:
                continue
            items.extend(values)
        if kind:
            items = [a for a in items if a.kind == kind]
        if stage:
            items = [a for a in items if a.stage == stage]
        return [artifact.as_dict() for artifact in items[:limit]]

    def resolve_artifact(self, path: str) -> Optional[str]:
        """Return an absolute path only when it lives inside a registered design."""
        real = os.path.realpath(os.path.abspath(path))
        for design in self._designs.values():
            root = design.path.rstrip(os.sep) + os.sep
            if real.startswith(root) or real == design.path:
                return real
        return None

    def artifact_counts(self, design_id: Optional[str] = None) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for key, values in self._artifacts.items():
            if design_id and key != design_id:
                continue
            for artifact in values:
                counts[artifact.kind] = counts.get(artifact.kind, 0) + 1
        return counts

    # ----------------------------------------------------------- conversations
    def create_conversation(self, title: str = "新对话", design_id: Optional[str] = None,
                            session_id: Optional[str] = None, run_id: Optional[str] = None) -> Conversation:
        conversation = Conversation(
            id=self._next_id("conv"),
            design_id=design_id,
            session_id=session_id,
            run_id=run_id,
            title=title,
        )
        self._conversations[conversation.id] = conversation
        return conversation

    def get_conversation(self, conversation_id: str) -> Optional[Conversation]:
        return self._conversations.get(conversation_id)

    def list_conversations(self) -> List[Dict[str, Any]]:
        return [c.as_dict() for c in self._conversations.values()]

    def append_message(self, conversation_id: str, role: str, content: str, **extra: Any) -> Dict[str, Any]:
        conversation = self._conversations.get(conversation_id)
        if conversation is None:
            conversation = self.create_conversation(title=conversation_id)
        message = {"role": role, "content": content, "ts": time.time()}
        message.update(extra)
        conversation.messages.append(message)
        self.bus.publish("conversation.message", conversation_id=conversation.id, message=message)
        return message

    # ------------------------------------------------------------------- views
    def context(self, session_id: Optional[str] = None, run_id: Optional[str] = None) -> Dict[str, Any]:
        """Everything an agent (or a human) needs to understand 'where am I'."""
        session = self._sessions.get(session_id) if session_id else None
        if session is None and self._sessions:
            session = next(iter(self._sessions.values()))
        meta = self._meta.get(session.id, {}) if session else {}
        run = self._runs.get(run_id or meta.get("current_run_id") or "")
        design = self._designs.get((meta.get("design_id") or (session.design_id if session else None)) or "")
        tail: List[str] = []
        if session is not None:
            tail = session.screen_lines(limit=40, include_history=True)
        return {
            "design": design.as_dict() if design else None,
            "session": self._session_view(session) if session else None,
            "run": run.as_dict() if run else None,
            "recent_runs": self.list_runs(session_id=session.id if session else None, limit=5),
            "artifacts": self.artifact_counts(design.id if design else None),
            "terminal_tail": tail,
            "cwd": session.cwd if session else None,
        }

    def snapshot(self) -> Dict[str, Any]:
        return {
            "pid": os.getpid(),
            "started_at": self.started_at,
            "uptime": time.time() - self.started_at,
            "uptime_text": duration(time.time() - self.started_at),
            "designs": self.list_designs(),
            "sessions": self.list_sessions(),
            "runs": self.list_runs(limit=50),
            "artifacts": self.artifact_counts(),
            "conversations": self.list_conversations(),
            "mcp": {"repo": self.mcp.repo, "entry": self.mcp.entry, "available": self.mcp.available},
            "config": {
                "port": self.config.get("port"),
                "default_cwd": self.config.get("default_cwd"),
                "shell": self.config.get("shell") or os.environ.get("SHELL", "/bin/bash"),
            },
        }
