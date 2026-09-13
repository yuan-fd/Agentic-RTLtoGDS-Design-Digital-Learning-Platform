from __future__ import annotations

"""Client for the official OpenROAD-MCP server (stdio, newline-delimited JSON-RPC).

The workbench keeps the official tool surface intact: all fifteen tools are
proxied through here, and the destructive ones are gated behind an explicit
``confirm`` flag rather than being quietly dropped from the UI.
"""

import asyncio
import json
import os
import shutil
from typing import Any, Dict, List, Optional

NODE_FALLBACKS = [
    os.path.expanduser("~/.nvm/versions/node"),
    "/usr/local/bin/node",
    "/usr/bin/node",
]

PROTOCOL_VERSION = "2025-06-18"

READ_ONLY = {
    "interactive_openroad_query",
    "list_interactive_sessions",
    "inspect_interactive_session",
    "get_session_history",
    "get_session_metrics",
    "list_report_images",
    "read_report_image",
    "get_orfs_job",
    "read_orfs_metrics",
    "grep_session_output",
}

DESTRUCTIVE = {
    "interactive_openroad_exec",
    "create_interactive_session",
    "terminate_interactive_session",
    "run_orfs_stage",
    "cancel_orfs_job",
}


def resolve_node() -> str:
    found = shutil.which("node")
    if found:
        return found
    for base in NODE_FALLBACKS:
        if os.path.isdir(base):
            for entry in sorted(os.listdir(base), reverse=True):
                candidate = os.path.join(base, entry, "bin", "node")
                if os.path.isfile(candidate):
                    return candidate
    for candidate in NODE_FALLBACKS[1:]:
        if os.path.isfile(candidate):
            return candidate
    return "node"


class MCPError(RuntimeError):
    pass


class MCPClient:
    def __init__(self, repo: str, node: Optional[str] = None, startup_timeout: float = 25.0) -> None:
        self.repo = os.path.abspath(repo)
        self.entry = os.path.join(self.repo, "typescript", "dist", "main.js")
        self.node = node or resolve_node()
        self.startup_timeout = startup_timeout
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._pending: Dict[int, asyncio.Future] = {}
        self._ident = 0
        self._lock = asyncio.Lock()
        self._catalog: Optional[List[Dict[str, Any]]] = None
        self.last_error: Optional[str] = None
        self._stderr_tail: List[str] = []
        self._stderr_task: Optional[asyncio.Task] = None

    # ---------------------------------------------------------------- lifecycle
    @property
    def available(self) -> bool:
        return os.path.isfile(self.entry)

    async def _ensure(self) -> None:
        if not self.available:
            raise MCPError("OpenROAD-MCP not found at %s" % self.entry)
        if self._proc is not None and self._proc.returncode is None:
            return
        self._pending.clear()
        self._proc = await asyncio.create_subprocess_exec(
            self.node,
            self.entry,
            cwd=self.repo,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._reader_task = asyncio.ensure_future(self._reader())
        self._stderr_task = asyncio.ensure_future(self._drain_stderr())
        await self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "openroad-workbench", "version": "0.1.0"},
            },
            timeout=self.startup_timeout,
        )
        await self._notify("notifications/initialized", {})
        self._catalog = None

    async def _notify(self, method: str, params: Dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise MCPError("MCP server is not running")
        payload = json.dumps({"jsonrpc": "2.0", "method": method, "params": params})
        self._proc.stdin.write((payload + "\n").encode())
        await self._proc.stdin.drain()

    async def _readline(self) -> bytes:
        if self._proc is None or self._proc.stdout is None:
            raise MCPError("MCP server is not running")
        return await self._proc.stdout.readline()

    async def _reader(self) -> None:
        try:
            while True:
                line = await self._readline()
                if not line:
                    break
                text = line.decode("utf-8", "replace").strip()
                if not text:
                    continue
                try:
                    message = json.loads(text)
                except Exception:
                    continue
                ident = message.get("id")
                if ident is None:
                    continue
                future = self._pending.pop(ident, None)
                if future is not None and not future.done():
                    future.set_result(message)
        except Exception as exc:  # pragma: no cover - transport failure
            self.last_error = str(exc)
        finally:
            for future in list(self._pending.values()):
                if not future.done():
                    future.set_exception(MCPError("MCP server exited"))
            self._pending.clear()

    async def _request(self, method: str, params: Dict[str, Any], timeout: float = 60.0) -> Dict[str, Any]:
        if self._proc is None or self._proc.stdin is None:
            raise MCPError("MCP server is not running")
        self._ident += 1
        ident = self._ident
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[ident] = future
        payload = json.dumps({"jsonrpc": "2.0", "id": ident, "method": method, "params": params})
        self._proc.stdin.write((payload + "\n").encode())
        await self._proc.stdin.drain()
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(ident, None)
            raise MCPError("MCP request %s timed out after %.0fs" % (method, timeout))

    async def _drain_stderr(self) -> None:
        """Keep the server's stderr instead of throwing it away: when the MCP
        child fails to start, its message is the only useful diagnostic."""
        if self._proc is None or self._proc.stderr is None:
            return
        try:
            while True:
                line = await self._proc.stderr.readline()
                if not line:
                    break
                self._stderr_tail.append(line.decode("utf-8", "replace").rstrip())
                del self._stderr_tail[:-40]
        except Exception:
            pass

    async def close(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            self._reader_task = None
        if self._proc is not None and self._proc.returncode is None:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        self._proc = None

    # ------------------------------------------------------------------- tools
    async def catalog(self, refresh: bool = False) -> List[Dict[str, Any]]:
        async with self._lock:
            if self._catalog is not None and not refresh:
                return self._catalog
            await self._ensure()
            response = await self._request("tools/list", {}, timeout=self.startup_timeout)
            tools = (response.get("result") or {}).get("tools") or []
            self._catalog = [
                {
                    "name": tool.get("name"),
                    "description": tool.get("description", ""),
                    "read_only": tool.get("name") in READ_ONLY,
                    "destructive": tool.get("name") in DESTRUCTIVE,
                    "input_schema": tool.get("inputSchema", {}),
                }
                for tool in tools
            ]
            return self._catalog

    async def call(self, tool: str, arguments: Dict[str, Any], confirm: bool = False) -> Dict[str, Any]:
        if tool not in READ_ONLY and tool not in DESTRUCTIVE:
            raise MCPError("tool is not admitted: %s" % tool)
        if tool in DESTRUCTIVE and not confirm:
            raise MCPError("confirm=true is required for state-changing tools")
        async with self._lock:
            await self._ensure()
            response = await self._request(
                "tools/call", {"name": tool, "arguments": arguments}, timeout=120.0
            )
        if "error" in response:
            raise MCPError(str(response["error"]))
        result = response.get("result") or {}
        blocks = result.get("content") or []
        text = ""
        images = []
        texts: List[str] = []
        for block in blocks:
            if block.get("type") == "text" and block.get("text"):
                texts.append(block["text"])
            if block.get("data"):
                images.append({"data": block["data"], "mimeType": block.get("mimeType", "image/webp")})
        text = "\n".join(texts)
        parsed: Any
        try:
            parsed = json.loads(text) if text else {}
        except Exception:
            parsed = {"output": text}
        return {
            "tool": tool,
            "result": parsed,
            "text": text,
            "images": images,
            "is_error": bool(result.get("isError")),
        }

    async def status(self) -> Dict[str, Any]:
        """Never blocks on the tool-call lock: a status probe must stay instant
        even while a 120 s ORFS stage call is in flight."""
        info = {
            "available": self.available,
            "repo": self.repo,
            "entry": self.entry,
            "node": self.node,
            "running": self._proc is not None and self._proc.returncode is None,
            "last_error": self.last_error,
            "catalog_loaded": self._catalog is not None,
            "tool_count": len(self._catalog) if self._catalog is not None else 0,
        }
        if self._stderr_tail:
            info["stderr_tail"] = self._stderr_tail[-10:]
        if not self.available:
            info["last_error"] = info["last_error"] or (
                "OpenROAD-MCP not found at %s (set mcp_repo in ~/.openroad-workbench/config.json)" % self.entry)
        return info
