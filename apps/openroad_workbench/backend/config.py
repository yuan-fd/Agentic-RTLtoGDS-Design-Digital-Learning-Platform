from __future__ import annotations

"""Workbench configuration and runtime paths.

Everything the daemon needs to find lives here so that the launcher, the TUI
and the tests agree.  Defaults are deliberately neutral: no network service, no
external dependency, no assumption that a model provider exists.
"""

import json
import os
from typing import Any, Dict, Optional

HOME = os.path.expanduser("~")
RUNTIME_DIR = os.path.join(HOME, ".openroad-workbench")
SHELL_DIR = os.path.join(RUNTIME_DIR, "shell")
CONFIG_PATH = os.path.join(RUNTIME_DIR, "config.json")

DEFAULT_MCP_CANDIDATES = [
    os.path.join(HOME, "openroad-mcp"),
    "/tmp/openroad-mcp-review",
]

DEFAULTS: Dict[str, Any] = {
    "mcp_repo": "",              # resolved by resolve_mcp_repo()
    "port": 8780,
    "host": "127.0.0.1",
    "shell": "",                 # empty -> $SHELL
    "default_cwd": HOME,
    "corpus_path": os.path.join(RUNTIME_DIR, "corpus"),
    "agent": {
        "provider": "null",      # null | openai
        "base_url": "",
        "model": "",
        "api_key_env": "OPENROAD_WORKBENCH_API_KEY",
    },
    "artifact_scan_interval": 10.0,
    "screen_lines": 400,
}


def ensure_dirs() -> None:
    for path in (RUNTIME_DIR, SHELL_DIR, os.path.join(RUNTIME_DIR, "logs")):
        os.makedirs(path, exist_ok=True)


def resolve_mcp_repo(explicit: Optional[str] = None) -> Optional[str]:
    """Find the official OpenROAD-MCP checkout, preferring a stable path."""
    if explicit:
        return explicit if os.path.isdir(explicit) else None
    for candidate in DEFAULT_MCP_CANDIDATES:
        if os.path.isfile(os.path.join(candidate, "typescript", "dist", "main.js")):
            return candidate
    return None


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    config = json.loads(json.dumps(DEFAULTS))
    target = path or CONFIG_PATH
    if os.path.isfile(target):
        try:
            with open(target, "r", encoding="utf-8") as handle:
                stored = json.load(handle)
            _deep_update(config, stored)
        except Exception:
            pass
    return config


def save_config(config: Dict[str, Any], path: Optional[str] = None) -> None:
    ensure_dirs()
    target = path or CONFIG_PATH
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2, ensure_ascii=False)


def _deep_update(base: Dict[str, Any], extra: Dict[str, Any]) -> None:
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value


def runtime_file(name: str) -> str:
    return os.path.join(RUNTIME_DIR, name)


def pid_file(port: int) -> str:
    return runtime_file("daemon-%d.pid" % port)


def info_file(port: int) -> str:
    return runtime_file("daemon-%d.json" % port)


def daemon_log(port: int) -> str:
    return runtime_file("logs/daemon-%d.log" % port)
