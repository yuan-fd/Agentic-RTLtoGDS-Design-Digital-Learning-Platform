from __future__ import annotations

"""HTTP/WebSocket surface.

Both clients (Textual TUI and the Web dashboard) talk to the daemon through this
API and *nothing else*, which is what keeps "TUI 显示的" and "Web 显示的" the same
truth.  The terminal socket carries rendered screen frames rather than raw bytes,
so the browser needs no terminal emulator.
"""

import asyncio
import json
import mimetypes
import os
import time
from typing import Any, Dict, Optional

from aiohttp import WSMsgType, web

from . import config as config_mod
from .agent import AgentService
from .core import Workbench
from .mcp_client import MCPError

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
MAX_TEXT_ARTIFACT = 2 * 1024 * 1024
FRAME_INTERVAL = 0.08
HEARTBEAT = 15.0


def json_response(data: Any, status: int = 200) -> web.Response:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return web.Response(body=body, status=status, content_type="application/json", charset="utf-8")


@web.middleware
async def error_middleware(request: web.Request, handler: Any) -> web.StreamResponse:
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except KeyError as exc:
        return json_response({"ok": False, "error": "not found: %s" % exc}, status=404)
    except (MCPError, ValueError) as exc:
        return json_response({"ok": False, "error": str(exc)}, status=400)
    except Exception as exc:  # pragma: no cover - defensive
        return json_response({"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}, status=500)


class Server:
    def __init__(self, workbench: Workbench, host: str = "127.0.0.1", port: int = 8780) -> None:
        self.workbench = workbench
        self.host = host
        self.port = port
        self.agent = AgentService(workbench, workbench.config)
        self.app = web.Application(middlewares=[error_middleware])
        self._add_routes()
        self._runner: Optional[web.AppRunner] = None

    # ------------------------------------------------------------------ routes
    def _add_routes(self) -> None:
        app = self.app
        app["wb"] = self.workbench
        app["agent"] = self.agent
        app.router.add_get("/api/status", self.handle_status)
        app.router.add_get("/api/state", self.handle_state)
        app.router.add_get("/api/events", self.handle_events)
        app.router.add_get("/api/config", self.handle_config)
        app.router.add_post("/api/config", self.handle_config_save)

        app.router.add_get("/api/designs", self.handle_designs)
        app.router.add_post("/api/designs", self.handle_design_register)
        app.router.add_get("/api/designs/{design_id}", self.handle_design_detail)

        app.router.add_get("/api/sessions", self.handle_sessions)
        app.router.add_post("/api/sessions", self.handle_session_create)
        app.router.add_get("/api/sessions/{sid}", self.handle_session_detail)
        app.router.add_post("/api/sessions/{sid}/input", self.handle_session_input)
        app.router.add_post("/api/sessions/{sid}/interrupt", self.handle_session_interrupt)
        app.router.add_post("/api/sessions/{sid}/terminate", self.handle_session_terminate)
        app.router.add_post("/api/sessions/{sid}/close", self.handle_session_close)
        app.router.add_post("/api/sessions/{sid}/rename", self.handle_session_rename)
        app.router.add_post("/api/sessions/{sid}/resize", self.handle_session_resize)
        app.router.add_get("/api/sessions/{sid}/screen", self.handle_session_screen)
        app.router.add_get("/api/sessions/{sid}/log", self.handle_session_log)

        app.router.add_get("/api/runs", self.handle_runs)
        app.router.add_get("/api/runs/{run_id}", self.handle_run_detail)
        app.router.add_post("/api/runs/{run_id}/cancel", self.handle_run_cancel)

        app.router.add_get("/api/artifacts", self.handle_artifacts)
        app.router.add_get("/api/artifact", self.handle_artifact_file)
        app.router.add_post("/api/artifacts/refresh", self.handle_artifacts_refresh)

        app.router.add_get("/api/tools", self.handle_tools)
        app.router.add_post("/api/tool", self.handle_tool_call)

        app.router.add_get("/api/agent", self.handle_agent_status)
        app.router.add_post("/api/agent/ask", self.handle_agent_ask)
        app.router.add_get("/api/conversations", self.handle_conversations)

        app.router.add_get("/ws/terminal/{sid}", self.handle_terminal_socket)

        app.router.add_get("/", self.handle_index)
        app.router.add_get("/static/{name}", self.handle_static)

    # ------------------------------------------------------------------ basics
    async def handle_status(self, request: web.Request) -> web.Response:
        """Kept compatible with the original acceptance command
        ``curl http://127.0.0.1:8780/api/status``."""
        workbench = self.workbench
        mcp_status = await workbench.mcp.status()
        return json_response({
            "ok": True,
            "transport": "stdio",
            "repo": workbench.mcp.repo,
            "tool_count": mcp_status.get("tool_count", 0),
            "app": "openroad-workbench",
            "version": "0.1.0",
            "pid": os.getpid(),
            "sessions": len(workbench.list_sessions()),
            "designs": len(workbench.list_designs()),
            "runs": len(workbench.list_runs(limit=10000)),
            "mcp": mcp_status,
            "agent": self.agent.status(),
        })

    async def handle_state(self, request: web.Request) -> web.Response:
        return json_response(self.workbench.snapshot())

    async def handle_config(self, request: web.Request) -> web.Response:
        return json_response(self.workbench.config)

    async def handle_config_save(self, request: web.Request) -> web.Response:
        payload = await _json_body(request)
        config = self.workbench.config
        for key, value in payload.items():
            if key in config and not isinstance(value, dict):
                config[key] = value
        config_mod.save_config(config)
        return json_response({"ok": True, "config": config})

    # ---------------------------------------------------------------- designs
    async def handle_designs(self, request: web.Request) -> web.Response:
        return json_response({"designs": self.workbench.list_designs()})

    async def handle_design_register(self, request: web.Request) -> web.Response:
        payload = await _json_body(request)
        path = payload.get("path")
        if not path:
            raise ValueError("path is required")
        design = self.workbench.register_design(path, payload.get("name"))
        await self.workbench.refresh_artifacts(design.id)
        return json_response({"ok": True, "design": design.as_dict()})

    async def handle_design_detail(self, request: web.Request) -> web.Response:
        design_id = request.match_info["design_id"]
        design = self.workbench.get_design(design_id)
        if design is None:
            raise KeyError(design_id)
        return json_response({
            "design": design.as_dict(),
            "artifacts": self.workbench.list_artifacts(design_id=design_id),
            "runs": self.workbench.list_runs(design_id=design_id, limit=50),
            "counts": self.workbench.artifact_counts(design_id),
        })

    # --------------------------------------------------------------- sessions
    async def handle_sessions(self, request: web.Request) -> web.Response:
        return json_response({"sessions": self.workbench.list_sessions()})

    async def handle_session_create(self, request: web.Request) -> web.Response:
        payload = await _json_body(request)
        session = self.workbench.create_session(
            name=payload.get("name"),
            cwd=payload.get("cwd"),
            argv=payload.get("argv"),
            design_id=payload.get("design_id"),
            cols=int(payload.get("cols") or 120),
            rows=int(payload.get("rows") or 32),
        )
        return json_response({"ok": True, "session": session})

    async def handle_session_detail(self, request: web.Request) -> web.Response:
        sid = request.match_info["sid"]
        session = self.workbench.get_session(sid)
        if session is None:
            raise KeyError(sid)
        data = self.workbench._session_view(session)
        data["screen"] = self.workbench.screen(sid, lines=int(request.query.get("lines", 200)))["screen"]
        data["runs"] = self.workbench.list_runs(session_id=sid, limit=20)
        return json_response(data)

    async def handle_session_input(self, request: web.Request) -> web.Response:
        payload = await _json_body(request)
        data = payload.get("data")
        if data is None:
            raise ValueError("data is required")
        return json_response(self.workbench.write_input(request.match_info["sid"], str(data)))

    async def handle_session_interrupt(self, request: web.Request) -> web.Response:
        return json_response(self.workbench.interrupt(request.match_info["sid"]))

    async def handle_session_terminate(self, request: web.Request) -> web.Response:
        return json_response(self.workbench.terminate(request.match_info["sid"]))

    async def handle_session_close(self, request: web.Request) -> web.Response:
        return json_response(self.workbench.close_session(request.match_info["sid"]))

    async def handle_session_rename(self, request: web.Request) -> web.Response:
        payload = await _json_body(request)
        return json_response({"ok": True, "session": self.workbench.rename_session(
            request.match_info["sid"], str(payload.get("name") or ""))})

    async def handle_session_resize(self, request: web.Request) -> web.Response:
        payload = await _json_body(request)
        return json_response(self.workbench.resize(
            request.match_info["sid"], int(payload.get("cols") or 120), int(payload.get("rows") or 32)))

    async def handle_session_screen(self, request: web.Request) -> web.Response:
        lines = int(request.query.get("lines", 200))
        return json_response(self.workbench.screen(request.match_info["sid"], lines=lines))

    async def handle_session_log(self, request: web.Request) -> web.Response:
        text = self.workbench.raw_log(request.match_info["sid"])
        return web.Response(text=text, content_type="text/plain", charset="utf-8")

    # ------------------------------------------------------------------- runs
    async def handle_runs(self, request: web.Request) -> web.Response:
        return json_response({"runs": self.workbench.list_runs(
            session_id=request.query.get("session_id"),
            design_id=request.query.get("design_id"),
            limit=int(request.query.get("limit", 100)),
        )})

    async def handle_run_detail(self, request: web.Request) -> web.Response:
        run = self.workbench.get_run(request.match_info["run_id"])
        if run is None:
            raise KeyError(request.match_info["run_id"])
        return json_response(run.as_dict())

    async def handle_run_cancel(self, request: web.Request) -> web.Response:
        return json_response(self.workbench.cancel_run(request.match_info["run_id"]))

    # -------------------------------------------------------------- artifacts
    async def handle_artifacts(self, request: web.Request) -> web.Response:
        return json_response({
            "artifacts": self.workbench.list_artifacts(
                design_id=request.query.get("design_id"),
                kind=request.query.get("kind"),
                stage=request.query.get("stage"),
                limit=int(request.query.get("limit", 400)),
            ),
            "counts": self.workbench.artifact_counts(request.query.get("design_id")),
        })

    async def handle_artifacts_refresh(self, request: web.Request) -> web.Response:
        payload = await _json_body(request)
        counts = await self.workbench.refresh_artifacts(payload.get("design_id"))
        return json_response({"ok": True, "counts": counts})

    async def handle_artifact_file(self, request: web.Request) -> web.StreamResponse:
        raw_path = request.query.get("path")
        if not raw_path:
            raise ValueError("path is required")
        path = self.workbench.resolve_artifact(raw_path)
        if path is None:
            raise KeyError("artifact is outside every registered design")
        if not os.path.isfile(path):
            raise KeyError(path)
        mime, _ = mimetypes.guess_type(path)
        if (mime or "").startswith("image/"):
            return web.FileResponse(path)
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            blob = handle.read(MAX_TEXT_ARTIFACT)
        truncated = size > MAX_TEXT_ARTIFACT
        text = blob.decode("utf-8", "replace")
        return web.Response(
            text=text,
            content_type="text/plain",
            charset="utf-8",
            headers={"x-owb-truncated": "1" if truncated else "0", "x-owb-size": str(size)},
        )

    # -------------------------------------------------------------------- MCP
    async def handle_tools(self, request: web.Request) -> web.Response:
        refresh = request.query.get("refresh") in ("1", "true")
        try:
            tools = await self.workbench.mcp.catalog(refresh=refresh)
        except MCPError as exc:
            return json_response({"ok": False, "error": str(exc), "tools": []}, status=200)
        return json_response({"tools": tools, "repo": self.workbench.mcp.repo})

    async def handle_tool_call(self, request: web.Request) -> web.Response:
        payload = await _json_body(request)
        tool = str(payload.get("tool") or "")
        if not tool:
            raise ValueError("tool is required")
        result = await self.workbench.mcp.call(tool, payload.get("arguments") or {}, bool(payload.get("confirm")))
        return json_response({"ok": True, **result})

    # ------------------------------------------------------------------ agent
    async def handle_agent_status(self, request: web.Request) -> web.Response:
        return json_response(self.agent.status())

    async def handle_conversations(self, request: web.Request) -> web.Response:
        return json_response({"conversations": self.workbench.list_conversations()})

    async def handle_agent_ask(self, request: web.Request) -> web.StreamResponse:
        payload = await _json_body(request)
        question = str(payload.get("question") or "").strip()
        if not question:
            raise ValueError("question is required")
        response = web.StreamResponse(headers={
            "content-type": "text/event-stream",
            "cache-control": "no-cache",
            "x-accel-buffering": "no",
        })
        await response.prepare(request)
        async for event in self.agent.answer(
            question,
            session_id=payload.get("session_id"),
            run_id=payload.get("run_id"),
            conversation_id=payload.get("conversation_id"),
        ):
            await response.write(("data: %s\n\n" % json.dumps(event, ensure_ascii=False)).encode("utf-8"))
        await response.write(b"data: {\"type\": \"end\"}\n\n")
        await response.write_eof()
        return response

    # ----------------------------------------------------------------- events
    async def handle_events(self, request: web.Request) -> web.StreamResponse:
        queue = self.workbench.bus.subscribe()
        response = web.StreamResponse(headers={
            "content-type": "text/event-stream",
            "cache-control": "no-cache",
            "x-accel-buffering": "no",
        })
        await response.prepare(request)
        try:
            await response.write(b": connected\n\n")
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT)
                except asyncio.TimeoutError:
                    await response.write(b": ping\n\n")
                    continue
                await response.write(("data: %s\n\n" % json.dumps(event, ensure_ascii=False)).encode("utf-8"))
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            self.workbench.bus.unsubscribe(queue)
        return response

    # -------------------------------------------------------------- websocket
    async def handle_terminal_socket(self, request: web.Request) -> web.StreamResponse:
        sid = request.match_info["sid"]
        session = self.workbench.get_session(sid)
        if session is None:
            raise KeyError(sid)
        ws = web.WebSocketResponse(heartbeat=30, max_msg_size=4 * 1024 * 1024)
        await ws.prepare(request)

        try:
            lines = int(request.query.get("lines", 400))
        except ValueError:
            lines = 400

        async def pump() -> None:
            last_version = -1
            last_alive = None
            while not ws.closed:
                current = self.workbench.get_session(sid)
                if current is None:
                    await _safe_send(ws, {"type": "closed", "session_id": sid})
                    break
                if current.version != last_version or current.alive != last_alive:
                    last_version = current.version
                    last_alive = current.alive
                    payload = self.workbench.screen(sid, lines=lines)
                    payload["type"] = "frame"
                    payload["cwd"] = current.cwd
                    await _safe_send(ws, payload)
                if not current.alive:
                    break
                await asyncio.sleep(FRAME_INTERVAL)

        async def reader() -> None:
            async for message in ws:
                if message.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(message.data)
                    except Exception:
                        continue
                    kind = data.get("type")
                    if kind == "input":
                        try:
                            self.workbench.write_input(sid, str(data.get("data") or ""))
                        except Exception:
                            pass
                    elif kind == "interrupt":
                        self.workbench.interrupt(sid)
                    elif kind == "resize":
                        self.workbench.resize(sid, int(data.get("cols") or 120), int(data.get("rows") or 32))
                elif message.type == WSMsgType.ERROR:
                    break

        await asyncio.gather(pump(), reader())
        if not ws.closed:
            await ws.close()
        return ws

    # ----------------------------------------------------------------- static
    async def handle_index(self, request: web.Request) -> web.Response:
        path = os.path.join(WEB_DIR, "index.html")
        if not os.path.isfile(path):
            return web.Response(text="web/index.html missing", status=500)
        return web.FileResponse(path)

    async def handle_static(self, request: web.Request) -> web.Response:
        name = os.path.basename(request.match_info["name"])
        path = os.path.join(WEB_DIR, name)
        if not os.path.isfile(path):
            raise KeyError(name)
        return web.FileResponse(path)

    # ------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        self._runner = web.AppRunner(self.app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None


async def _safe_send(ws: web.WebSocketResponse, payload: Dict[str, Any]) -> None:
    try:
        await ws.send_json(payload, dumps=lambda obj: json.dumps(obj, ensure_ascii=False))
    except (ConnectionResetError, RuntimeError, asyncio.CancelledError):
        pass


async def _json_body(request: web.Request) -> Dict[str, Any]:
    if request.can_read_body:
        try:
            data = await request.json()
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}
    return {}


def build_app(workbench: Workbench, host: str = "127.0.0.1", port: int = 8780) -> web.Application:
    return Server(workbench, host, port).app
