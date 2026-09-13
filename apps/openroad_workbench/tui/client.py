from __future__ import annotations

"""Async client used by the TUI to talk to the workbench daemon.

The TUI owns no state of its own: every screen, run and artifact it shows comes
from the daemon, which is the same daemon the browser talks to.
"""

import asyncio
import json
from typing import Any, AsyncIterator, Dict, List, Optional

import aiohttp


class DaemonError(RuntimeError):
    pass


class DaemonClient:
    def __init__(self, base_url: str, timeout: float = 25.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session: Optional[aiohttp.ClientSession] = None
        self._stream: Optional[aiohttp.ClientSession] = None

    async def start(self) -> None:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout))
        if self._stream is None or self._stream.closed:
            self._stream = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_read=None))

    async def close(self) -> None:
        for session in (self._session, self._stream):
            if session is not None and not session.closed:
                await session.close()
        self._session = None
        self._stream = None

    # ------------------------------------------------------------------ basics
    async def get(self, path: str, **params: Any) -> Dict[str, Any]:
        await self.start()
        assert self._session is not None
        async with self._session.get(self.base_url + path, params=params) as response:
            data = await response.json(content_type=None)
            if response.status >= 400:
                raise DaemonError(str(data.get("error") or response.status))
            return data

    async def post(self, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        await self.start()
        assert self._session is not None
        async with self._session.post(self.base_url + path, json=payload or {}) as response:
            data = await response.json(content_type=None)
            if response.status >= 400:
                raise DaemonError(str(data.get("error") or response.status))
            return data

    # ------------------------------------------------------------------ state
    async def status(self) -> Dict[str, Any]:
        return await self.get("/api/status")

    async def state(self) -> Dict[str, Any]:
        return await self.get("/api/state")

    async def screen(self, session_id: str, lines: int = 400) -> Dict[str, Any]:
        return await self.get("/api/sessions/%s/screen" % session_id, lines=lines)

    async def runs(self, limit: int = 50) -> List[Dict[str, Any]]:
        return (await self.get("/api/runs", limit=limit)).get("runs", [])

    async def artifacts(self, design_id: Optional[str] = None, kind: Optional[str] = None) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {}
        if design_id:
            params["design_id"] = design_id
        if kind:
            params["kind"] = kind
        return (await self.get("/api/artifacts", **params)).get("artifacts", [])

    # --------------------------------------------------------------- commands
    async def send_input(self, session_id: str, data: str) -> None:
        await self.post("/api/sessions/%s/input" % session_id, {"data": data})

    async def fill(self, session_id: str, text: str) -> Dict[str, Any]:
        """Ask the daemon to insert text into the command line (never executes)."""
        return await self.post("/api/sessions/%s/fill" % session_id, {"text": text})

    async def interrupt(self, session_id: str) -> None:
        await self.post("/api/sessions/%s/interrupt" % session_id)

    async def resize(self, session_id: str, cols: int, rows: int) -> None:
        await self.post("/api/sessions/%s/resize" % session_id, {"cols": cols, "rows": rows})

    async def create_session(self, name: Optional[str] = None, cwd: Optional[str] = None) -> Dict[str, Any]:
        return await self.post("/api/sessions", {"name": name, "cwd": cwd})

    async def close_session(self, session_id: str) -> None:
        await self.post("/api/sessions/%s/close" % session_id)

    # ----------------------------------------------------------------- streams
    async def events(self) -> AsyncIterator[Dict[str, Any]]:
        await self.start()
        assert self._stream is not None
        async with self._stream.get(self.base_url + "/api/events") as response:
            async for raw in response.content:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                try:
                    yield json.loads(line[5:].strip())
                except Exception:
                    continue

    async def ask(self, question: str, session_id: Optional[str] = None,
                  conversation_id: Optional[str] = None) -> AsyncIterator[Dict[str, Any]]:
        await self.start()
        assert self._stream is not None
        payload = {"question": question, "session_id": session_id, "conversation_id": conversation_id}
        async with self._stream.post(self.base_url + "/api/agent/ask", json=payload) as response:
            async for raw in response.content:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                try:
                    event = json.loads(line[5:].strip())
                except Exception:
                    continue
                if event.get("type") == "end":
                    break
                yield event

    async def terminal_socket(self, session_id: str, lines: int = 400):
        await self.start()
        assert self._stream is not None
        return await self._stream.ws_connect(
            "%s/ws/terminal/%s?lines=%d" % (self.base_url, session_id, lines)
        )
