from __future__ import annotations

"""``openroad-workbench`` command line entry point.

Typical use::

    openroad-workbench                     # start daemon + TUI + web dashboard
    openroad-workbench --design ~/designs/gcd
    openroad-workbench --no-tui            # daemon only, print the web URL
    openroad-workbench --status            # JSON status of the running daemon
    openroad-workbench --stop

The daemon is started detached so that closing the TUI does not kill a running
OpenROAD job; reopen with the same command and the TUI re-attaches to the same
sessions.
"""

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

from .backend import config as config_mod

PKG_DIR = os.path.dirname(os.path.abspath(__file__))
APPS_DIR = os.path.dirname(PKG_DIR)


# --------------------------------------------------------------------- helpers
def http_get(url: str, timeout: float = 2.0) -> Optional[Dict[str, Any]]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def daemon_status(host: str, port: int) -> Optional[Dict[str, Any]]:
    data = http_get("http://%s:%d/api/status" % (host, port))
    if data and data.get("app") == "openroad-workbench":
        return data
    return None


def wait_ready(host: str, port: int, timeout: float = 30.0) -> Optional[Dict[str, Any]]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = daemon_status(host, port)
        if status:
            return status
        time.sleep(0.25)
    return None


def daemon_env() -> Dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = APPS_DIR + (os.pathsep + existing if existing else "")
    return env


def spawn_daemon(host: str, port: int, design: Optional[str], cwd: Optional[str],
                 mcp_repo: Optional[str], log_path: str) -> int:
    config_mod.ensure_dirs()
    argv = [
        sys.executable, "-m", "openroad_workbench.backend.daemon",
        "--host", host, "--port", str(port),
    ]
    if design:
        argv += ["--design", design]
    if cwd:
        argv += ["--cwd", cwd]
    if mcp_repo:
        argv += ["--mcp-repo", mcp_repo]
    with open(log_path, "ab") as log:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
            env=daemon_env(),
            cwd=os.path.expanduser("~"),
        )
    return process.pid


def pick_port(host: str, preferred: int, attempts: int = 20) -> Tuple[int, Optional[str]]:
    """Return a port that is either free or already ours."""
    for offset in range(attempts):
        candidate = preferred + offset
        if daemon_status(host, candidate):
            return candidate, "attached"
        if not port_open(host, candidate):
            return candidate, "free" if offset == 0 else "moved"
    raise SystemExit("no free port near %d" % preferred)


def find_daemon(host: str, preferred: int, span: int = 20):
    """Locate a *running* daemon.  Never drifts onto a free port the way
    pick_port does, which used to make --status/--stop report "not running"
    whenever the daemon had been started on a neighbouring port."""
    for offset in range(span):
        port = preferred + offset
        status = daemon_status(host, port)
        if status:
            return port, status
    return None, None


def stop_daemon(host: str, port: int) -> int:
    status = daemon_status(host, port)
    if not status:
        print("no openroad-workbench daemon on %s:%d" % (host, port))
        return 1
    pid = int(status.get("pid") or 0)
    if pid <= 0:
        print("daemon reported no pid")
        return 1
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        print("cannot signal pid %d: %s" % (pid, exc))
        return 1
    deadline = time.time() + 15
    while time.time() < deadline:
        if not daemon_status(host, port):
            print("stopped openroad-workbench (pid %d)" % pid)
            return 0
        time.sleep(0.25)
    print("daemon pid %d did not stop in time" % pid)
    return 1


# ------------------------------------------------------------------------ main
def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="openroad-workbench",
        description="Terminal-first OpenROAD workbench (real PTY + TUI + web dashboard)",
    )
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--design", default=None, help="design directory to open")
    parser.add_argument("--cwd", default=None, help="working directory for the main terminal")
    parser.add_argument("--mcp-repo", default=None, help="path to the official OpenROAD-MCP checkout")
    parser.add_argument("--no-tui", action="store_true", help="start the daemon only")
    parser.add_argument("--no-web", action="store_true", help="do not print the dashboard URL")
    parser.add_argument("--status", action="store_true", help="print daemon status as JSON")
    parser.add_argument("--stop", action="store_true", help="stop the daemon")
    parser.add_argument("--log", action="store_true", help="tail the daemon log")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    config = config_mod.load_config()
    host = args.host or config.get("host") or "127.0.0.1"
    preferred = args.port or int(config.get("port") or 8780)

    if args.status:
        port, status = find_daemon(host, preferred)
        if not status:
            print(json.dumps({"ok": False, "error": "daemon not running"}, indent=2))
            return 1
        print(json.dumps(status, indent=2, ensure_ascii=False))
        return 0

    if args.stop:
        port, _ = find_daemon(host, preferred)
        if port is None:
            print("no openroad-workbench daemon near %s:%d" % (host, preferred))
            return 1
        return stop_daemon(host, port)

    if args.log:
        path = config_mod.daemon_log(preferred)
        if not os.path.isfile(path):
            print("no log at %s" % path)
            return 1
        return subprocess.call(["tail", "-n", "200", "-f", path])

    port, mode = pick_port(host, preferred)
    status = daemon_status(host, port)
    if status is None:
        log_path = config_mod.daemon_log(port)
        pid = spawn_daemon(host, port, args.design, args.cwd, args.mcp_repo, log_path)
        status = wait_ready(host, port)
        if status is None:
            print("daemon failed to start; see %s" % log_path, file=sys.stderr)
            try:
                print(open(log_path, "r", encoding="utf-8", errors="replace").read()[-4000:], file=sys.stderr)
            except OSError:
                pass
            return 1
        if mode == "moved":
            print("port %d was busy, using %d instead" % (preferred, port))
        del pid

    url = "http://%s:%d" % (host, port)
    if not args.no_web:
        print("OpenROAD Workbench dashboard: %s" % url)
        print("  (SSH users: forward this port, e.g. ssh -L %d:127.0.0.1:%d %s)" % (port, port, _ssh_target()))

    if args.no_tui:
        if os.environ.get("OWB_FOREGROUND") == "1":
            while True:
                time.sleep(5)
        return 0

    try:
        from .tui.app import run_tui
    except Exception as exc:  # pragma: no cover
        print("TUI unavailable (%s); daemon is running at %s" % (exc, url), file=sys.stderr)
        return 1
    return run_tui(base_url=url, status=status)


def _ssh_target() -> str:
    connection = os.environ.get("SSH_CONNECTION", "").split()
    if len(connection) >= 3:
        return "%s@%s" % (os.environ.get("USER", "user"), connection[2])
    return "user@host"


if __name__ == "__main__":
    sys.exit(main())
