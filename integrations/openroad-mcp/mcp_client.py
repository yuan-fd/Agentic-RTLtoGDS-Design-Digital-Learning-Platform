from __future__ import annotations

"""Minimal MCP stdio client for the official OpenROAD-MCP server.

Deliberately dependency-free (standard library only) and transparent: it speaks
the MCP JSON-RPC protocol straight to the upstream `typescript/dist/main.js`, so
whatever you see here is what the official server actually sent.  Nothing is
translated, summarised or re-implemented.

Protocol notes
--------------
* MCP over stdio is newline-delimited JSON-RPC 2.0.
* Handshake: `initialize` -> `notifications/initialized` -> `tools/list`.
* One request is in flight at a time; notifications are set aside.
"""

import json
import os
import queue
import shutil
import subprocess
import threading
from collections import deque
from typing import Any, Dict, List, Optional

PROTOCOL_VERSION = "2025-06-18"

REPO_CANDIDATES = [
    "~/openroad-mcp",
    "~/openroad-mcp-review",
    "/tmp/openroad-mcp-review",
]

NODE_SEARCH = [
    "~/.nvm/versions/node",
]


class MCPError(RuntimeError):
    pass


def resolve_repo(explicit: Optional[str] = None) -> str:
    """Locate the official checkout (must contain typescript/dist/main.js)."""
    candidates: List[str] = []
    if explicit:
        candidates.append(explicit)
    env = os.environ.get("OPENROAD_MCP_REPO")
    if env:
        candidates.append(env)
    candidates.extend(REPO_CANDIDATES)
    for candidate in candidates:
        path = os.path.abspath(os.path.expanduser(candidate))
        if os.path.isfile(os.path.join(path, "typescript", "dist", "main.js")):
            return path
    raise MCPError(
        "OpenROAD-MCP checkout not found. Pass --repo, set OPENROAD_MCP_REPO, or clone it:\n"
        "  git clone https://github.com/The-OpenROAD-Project/OpenROAD-MCP.git ~/openroad-mcp\n"
        "  cd ~/openroad-mcp/typescript && npm install && npm run build"
    )


def resolve_node(explicit: Optional[str] = None) -> str:
    if explicit:
        return explicit
    found = shutil.which("node")
    if found:
        return found
    for base in NODE_SEARCH:
        base_path = os.path.expanduser(base)
        if os.path.isdir(base_path):
            for entry in sorted(os.listdir(base_path), reverse=True):
                candidate = os.path.join(base_path, entry, "bin", "node")
                if os.path.isfile(candidate):
                    return candidate
    return "node"


class MCPStdioClient:
    """Spawns the official server and talks MCP to it."""

    def __init__(
        self,
        repo: Optional[str] = None,
        node: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
        request_timeout: float = 120.0,
    ) -> None:
        self.repo = resolve_repo(repo)
        self.entry = os.path.join(self.repo, "typescript", "dist", "main.js")
        self.node = resolve_node(node)
        self.cwd = cwd or self.repo
        self.request_timeout = request_timeout
        self.extra_env = dict(env or {})
        self.proc: Optional[subprocess.Popen] = None
        self.server_info: Dict[str, Any] = {}
        self._responses: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self._notifications: List[Dict[str, Any]] = []
        self.stderr_tail: deque = deque(maxlen=80)
        self._ident = 0
        self._lock = threading.Lock()

    # ------------------------------------------------------------- lifecycle
    def __enter__(self) -> "MCPStdioClient":
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def start(self) -> Dict[str, Any]:
        child_env = dict(os.environ)
        child_env.update(self.extra_env)
        self.proc = subprocess.Popen(
            [self.node, self.entry],
            cwd=self.cwd,
            env=child_env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        result = self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "openroad-mcp-console", "version": "1.0"},
            },
        )
        self.server_info = result.get("result", {}).get("serverInfo", {})
        self.notify("notifications/initialized", {})
        return self.server_info

    def close(self) -> None:
        proc, self.proc = self.proc, None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    # --------------------------------------------------------------- plumbing
    def _read_stdout(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        for raw in self.proc.stdout:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except Exception:
                continue
            if "id" in message:
                self._responses.put(message)
            else:
                self._notifications.append(message)
        self._responses.put({"__eof__": True})

    def _read_stderr(self) -> None:
        assert self.proc is not None and self.proc.stderr is not None
        for raw in self.proc.stderr:
            self.stderr_tail.append(raw.decode("utf-8", "replace").rstrip())

    def _write(self, payload: Dict[str, Any]) -> None:
        if self.proc is None or self.proc.stdin is None:
            raise MCPError("server is not running")
        data = (json.dumps(payload) + "\n").encode()
        with self._lock:
            self.proc.stdin.write(data)
            self.proc.stdin.flush()

    def notify(self, method: str, params: Dict[str, Any]) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method: str, params: Dict[str, Any], timeout: Optional[float] = None) -> Dict[str, Any]:
        self._ident += 1
        ident = self._ident
        self._write({"jsonrpc": "2.0", "id": ident, "method": method, "params": params})
        deadline = timeout if timeout is not None else self.request_timeout
        while True:
            try:
                message = self._responses.get(timeout=deadline)
            except queue.Empty:
                raise MCPError(
                    "no reply to %s within %.0fs%s" % (
                        method, deadline,
                        ("\nserver stderr:\n" + "\n".join(self.stderr_tail)) if self.stderr_tail else "",
                    )
                )
            if message.get("__eof__"):
                raise MCPError(
                    "server exited during %s%s" % (
                        method,
                        ("\nserver stderr:\n" + "\n".join(self.stderr_tail)) if self.stderr_tail else "",
                    )
                )
            if message.get("id") == ident:
                return message
            self._notifications.append(message)

    # ------------------------------------------------------------------- tools
    def list_tools(self) -> List[Dict[str, Any]]:
        response = self.request("tools/list", {})
        if "error" in response:
            raise MCPError(str(response["error"]))
        return response.get("result", {}).get("tools", [])

    def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None,
                  timeout: Optional[float] = None) -> Dict[str, Any]:
        """Return the raw JSON-RPC response for a tools/call."""
        return self.request("tools/call", {"name": name, "arguments": arguments or {}}, timeout=timeout)


def result_text(response: Dict[str, Any]) -> str:
    """Concatenate the text blocks of a tools/call response."""
    blocks = (response.get("result") or {}).get("content") or []
    return "\n".join(block.get("text", "") for block in blocks if block.get("text"))


def result_images(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    blocks = (response.get("result") or {}).get("content") or []
    return [block for block in blocks if block.get("data")]


def parse_json(text: str, what: str = "JSON") -> Any:
    try:
        return json.loads(text)
    except Exception as exc:
        raise MCPError("%s could not be parsed: %s" % (what, exc))
