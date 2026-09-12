#!/usr/bin/env python3
"""Read-only capability probe for the official OpenROAD-MCP server.

The probe only performs the MCP ``initialize`` handshake and ``tools/list``.
It never creates an OpenROAD session, sends Tcl, runs ORFS, installs packages,
or writes into the repository.  ``npx --no-install`` is used deliberately:
the probe may use an already cached package, but it will not download one.
"""

from __future__ import annotations

import argparse
import json
import os
import selectors
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


PROTOCOL_VERSION = "2025-06-18"
DEFAULT_REPO = Path("/tmp/openroad-mcp-review")
DEFAULT_TIMEOUT = 15.0


class ProbeError(RuntimeError):
    """A reproducible probe failure, reported without a traceback."""


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    """Stop the server and any child processes spawned during the probe."""

    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=2)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        pass
    except OSError:
        process.terminate()
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            process.kill()
        process.wait(timeout=2)


def _send(process: subprocess.Popen[bytes], message: dict[str, Any]) -> None:
    """Write one newline-delimited JSON-RPC message used by MCP stdio."""

    payload = (json.dumps(message, separators=(",", ":")) + "\n").encode()
    assert process.stdin is not None
    process.stdin.write(payload)
    process.stdin.flush()


def _read_message(
    process: subprocess.Popen[bytes], selector: selectors.BaseSelector, deadline: float
) -> dict[str, Any]:
    """Read one newline-framed MCP message, tolerating blank/non-JSON lines."""

    assert process.stdout is not None
    while time.monotonic() < deadline:
        remaining = max(0.01, deadline - time.monotonic())
        events = selector.select(remaining)
        if not events:
            continue
        raw = process.stdout.readline()
        if not raw:
            detail = process.stderr.read().decode(errors="replace") if process.stderr else ""
            raise ProbeError(
                f"MCP process exited before replying (exit={process.poll()}); "
                f"stderr={detail[-1000:].strip()!r}"
            )
        line = raw.decode(errors="replace").strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            # MCP stdio reserves stdout for JSON, but ignoring a stray line makes
            # diagnostics useful with wrappers that print a startup banner.
            continue
        if isinstance(value, dict):
            return value
    raise ProbeError("Timed out waiting for MCP JSON-RPC response")


def _command(repo: Path, mode: str) -> tuple[list[str], str]:
    node = shutil.which("node")
    if node is None:
        raise ProbeError("Node.js is not on PATH; install Node.js 22+ before probing OpenROAD-MCP")

    dist = repo / "typescript" / "dist" / "main.js"
    if mode in {"auto", "repo"} and dist.is_file():
        return [node, str(dist)], "repo-dist"
    if mode == "repo":
        raise ProbeError(
            f"Repository build not found at {dist}; run 'cd {repo / 'typescript'} && "
            "npm ci && npm run build', then rerun this probe"
        )

    npx = shutil.which("npx")
    if npx is None:
        raise ProbeError("npx is not on PATH and no repository dist/main.js was found")
    # --no-install is important: this is a capability probe, not an installer.
    return [npx, "--no-install", "openroad-mcp"], "npx-no-install"


def probe(repo: Path, mode: str, timeout: float) -> dict[str, Any]:
    command, source = _command(repo, mode)
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=str(repo if source == "repo-dist" else Path.cwd()),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        env=dict(os.environ),
    )
    selector = selectors.DefaultSelector()
    assert process.stdout is not None
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        deadline = time.monotonic() + timeout
        _send(
            process,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "openroad-platform-probe", "version": "1.0"},
                },
            },
        )
        initialized = _read_message(process, selector, deadline)
        if initialized.get("id") != 1 or "result" not in initialized:
            raise ProbeError(f"MCP initialize failed: {json.dumps(initialized, sort_keys=True)}")
        _send(process, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        _send(process, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        listed = _read_message(process, selector, deadline)
        if listed.get("id") != 2 or "result" not in listed:
            raise ProbeError(f"MCP tools/list failed: {json.dumps(listed, sort_keys=True)}")
        tools = listed["result"].get("tools")
        if not isinstance(tools, list):
            raise ProbeError("MCP tools/list returned no tools array")
        names = [item.get("name") for item in tools if isinstance(item, dict)]
        return {
            "status": "ok",
            "source": source,
            "command": command,
            "server": initialized["result"].get("serverInfo"),
            "protocol_version": initialized["result"].get("protocolVersion"),
            "tool_count": len(names),
            "tools": names,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
    finally:
        selector.close()
        _kill_process_group(process)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO, help="OpenROAD-MCP checkout")
    parser.add_argument("--mode", choices=("auto", "repo", "npx"), default="auto")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    try:
        result = probe(args.repo.expanduser().resolve(), args.mode, args.timeout)
    except (OSError, ProbeError) as exc:
        result = {
            "status": "unavailable",
            "mode": args.mode,
            "repo": str(args.repo.expanduser().resolve()),
            "diagnostic": str(exc),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
