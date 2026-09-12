#!/usr/bin/env python3
"""Run one bounded, read-only query through a server-owned OpenROAD-MCP build."""
from __future__ import annotations

import argparse
import json
import os
import selectors
import signal
import subprocess
import sys
import time
from pathlib import Path

ALLOWED = ("version", "help", "report_", "get_", "check_", "sta")


def _valid(command: str) -> bool:
    text = command.strip()
    if not text or any(token in text for token in (";", "\n", "\r", "[", "]", "$") ):
        return False
    verb = text.split(None, 1)[0]
    return any(verb == item or verb.startswith(item) for item in ALLOWED)


def _read(process: subprocess.Popen[bytes], selector: selectors.BaseSelector, deadline: float) -> dict:
    assert process.stdout is not None
    while time.monotonic() < deadline:
        if not selector.select(max(.01, deadline - time.monotonic())):
            continue
        line = process.stdout.readline().decode(errors="replace").strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise TimeoutError("MCP query timed out")


def query(repo: Path, command: str, timeout: float, *, tool: str = "interactive_openroad_query", arguments: dict | None = None) -> dict:
    if not _valid(command):
        raise ValueError("only read-only OpenROAD query verbs are allowed")
    node = os.environ.get("OPENROAD_MCP_NODE") or "node"
    process = subprocess.Popen(
        [node, str(repo / "typescript" / "dist" / "main.js")],
        cwd=str(repo), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True,
    )
    selector = selectors.DefaultSelector()
    assert process.stdout is not None and process.stdin is not None
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        def send(payload: dict) -> None:
            process.stdin.write((json.dumps(payload, separators=(",", ":")) + "\n").encode())
            process.stdin.flush()
        deadline = time.monotonic() + timeout
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "openroad-platform", "version": "1"}}})
        initialized = _read(process, selector, deadline)
        if "result" not in initialized:
            raise RuntimeError("MCP initialize failed")
        send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        call_args = arguments if arguments is not None else {"command": command, "timeout_ms": max(1000, int(timeout * 1000))}
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": tool, "arguments": call_args}})
        response = _read(process, selector, deadline)
        if response.get("id") != 2 or "result" not in response:
            raise RuntimeError(str(response.get("error") or "MCP query failed"))
        content = response["result"].get("content") or []
        text = next((item.get("text") for item in content if isinstance(item, dict)
                     and isinstance(item.get("text"), str)), "")
        images = [{"data": item.get("data"), "mimeType": item.get("mimeType")}
                  for item in content if isinstance(item, dict) and isinstance(item.get("data"), str)]
        return {"status": "ok", "command": command, "tool": tool, "result": json.loads(text) if text else {},
                **({"images": images} if images else {}),
                "source": "openroad-mcp-stdio"}
    finally:
        selector.close()
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=2)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--command", required=True)
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--tool", default="interactive_openroad_query")
    parser.add_argument("--arguments", default="")
    args = parser.parse_args()
    try:
        arguments = json.loads(args.arguments) if args.arguments else None
        print(json.dumps(query(args.repo.expanduser().resolve(), args.command, args.timeout, tool=args.tool, arguments=arguments), ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
