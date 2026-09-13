from __future__ import annotations

"""The workbench daemon.

Runs one :class:`Workbench` plus the HTTP/WebSocket server.  Both the TUI and
the browser attach to this process, so "共享同一后台状态" is an architectural
fact rather than a synchronisation problem.
"""

import argparse
import asyncio
import json
import os
import signal
import sys
import time
from typing import Any, Dict, Optional

from . import config as config_mod
from .core import Workbench
from .server import Server


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="openroad-workbench-daemon", add_help=True)
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--mcp-repo", default=None)
    parser.add_argument("--design", default=None, help="register this design directory")
    parser.add_argument("--cwd", default=None, help="working directory for the main terminal")
    parser.add_argument("--no-main-session", action="store_true")
    return parser.parse_args(argv)


def build_config(args: argparse.Namespace) -> Dict[str, Any]:
    config = config_mod.load_config()
    if args.host:
        config["host"] = args.host
    if args.port:
        config["port"] = args.port
    repo = config_mod.resolve_mcp_repo(args.mcp_repo or config.get("mcp_repo"))
    config["mcp_repo"] = repo or ""
    if args.design:
        config["default_cwd"] = os.path.abspath(os.path.expanduser(args.design))
    elif args.cwd:
        config["default_cwd"] = os.path.abspath(os.path.expanduser(args.cwd))
    return config


def already_running(host: str, port: int) -> Optional[int]:
    """Return the pid of a live workbench daemon on this port, if any."""
    import urllib.request

    try:
        with urllib.request.urlopen("http://%s:%d/api/status" % (host, port), timeout=2) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    if data.get("app") == "openroad-workbench":
        return int(data.get("pid") or 0)
    return None


async def run(args: argparse.Namespace) -> int:
    config = build_config(args)
    existing = already_running(config["host"], config["port"])
    if existing:
        print("OpenROAD Workbench already running on %s:%d (pid %d); refusing to start a second one."
              % (config["host"], config["port"], existing), file=sys.stderr)
        return 1
    loop = asyncio.get_running_loop()
    workbench = Workbench(loop, config)

    if args.design:
        workbench.register_design(config["default_cwd"])

    if args.no_main_session:
        config["_skip_main_session"] = True
    await workbench.start()

    server = Server(workbench, config["host"], config["port"])
    await server.start()

    config_mod.ensure_dirs()
    info = {
        "pid": os.getpid(),
        "host": config["host"],
        "port": config["port"],
        "url": "http://%s:%d" % (config["host"], config["port"]),
        "mcp_repo": config["mcp_repo"],
        "started_at": time.time(),
    }
    with open(config_mod.info_file(config["port"]), "w", encoding="utf-8") as handle:
        json.dump(info, handle, indent=2)
    with open(config_mod.pid_file(config["port"]), "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))

    print("OpenROAD Workbench: %s" % info["url"], flush=True)
    print("  design   : %s" % (config.get("default_cwd") or "-"), flush=True)
    print("  mcp repo : %s" % (config["mcp_repo"] or "(not found)"), flush=True)

    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # pragma: no cover
            pass

    await stop.wait()
    print("OpenROAD Workbench: shutting down", flush=True)
    await server.stop()
    await workbench.shutdown()
    for path in (config_mod.pid_file(config["port"]), config_mod.info_file(config["port"])):
        try:
            os.remove(path)
        except OSError:
            pass
    return 0


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:  # pragma: no cover
        return 130


if __name__ == "__main__":
    sys.exit(main())
