from __future__ import annotations

"""Workbench domain model.

User-facing rule (see WORKBENCH_SPEC.md): the interface shows names, never
hashes.  Every object therefore carries both a compact technical ``id``
(``term-1``, ``run-7`` – readable on purpose, no UUIDs) and a human ``name``
that the user can rename.
"""

import os
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


def _now() -> float:
    return time.time()


def short_time(ts: Optional[float]) -> str:
    if not ts:
        return "-"
    return time.strftime("%H:%M:%S", time.localtime(ts))


def duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "-"
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return "%.1fs" % seconds
    minutes, sec = divmod(int(seconds), 60)
    if minutes < 60:
        return "%dm%02ds" % (minutes, sec)
    hours, minutes = divmod(minutes, 60)
    return "%dh%02dm" % (hours, minutes)


STAGE_ORDER = ["synth", "floorplan", "place", "cts", "grt", "route", "finish"]


@dataclass
class Design:
    """A design project: the top-level entity the user tracks."""

    id: str
    name: str
    path: str
    created_at: float = field(default_factory=_now)
    last_active_at: float = field(default_factory=_now)
    platform: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["exists"] = os.path.isdir(self.path)
        return data


@dataclass
class Run:
    """One tracked execution inside a terminal session."""

    id: str
    session_id: str
    design_id: Optional[str]
    command: str
    cwd: Optional[str] = None
    started_at: float = field(default_factory=_now)
    finished_at: Optional[float] = None
    exit_code: Optional[int] = None
    status: str = "running"  # running | success | failed | cancelled | unknown
    stages: List[str] = field(default_factory=list)
    provisional: bool = True  # command text not yet confirmed by shell integration
    output_head: str = ""
    output_tail: str = ""

    @property
    def name(self) -> str:
        return "%s · %s" % (self.command or "(unknown)", short_time(self.started_at))

    @property
    def elapsed(self) -> Optional[float]:
        end = self.finished_at if self.finished_at else _now()
        return end - self.started_at

    def as_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["name"] = self.name
        data["elapsed"] = self.elapsed
        data["elapsed_text"] = duration(self.elapsed)
        data["started_text"] = short_time(self.started_at)
        return data


@dataclass
class Artifact:
    """A produced file: report, log, image, metric or design data."""

    id: str
    design_id: str
    path: str
    kind: str  # report | log | image | metric | data | script | other
    stage: Optional[str] = None
    run_id: Optional[str] = None
    size: int = 0
    mtime: float = 0.0

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    @property
    def rel_path(self) -> str:
        return self.path

    def as_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["name"] = self.name
        data["mtime_text"] = short_time(self.mtime)
        data["size_text"] = _human_size(self.size)
        return data


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "K", "M", "G"):
        if value < 1024 or unit == "G":
            return ("%d%s" % (value, unit)) if unit == "B" else ("%.1f%s" % (value, unit))
        value /= 1024.0
    return str(size)


@dataclass
class Conversation:
    """An agent conversation, bound to a design and optionally a session/run."""

    id: str
    design_id: Optional[str] = None
    session_id: Optional[str] = None
    run_id: Optional[str] = None
    title: str = "新对话"
    created_at: float = field(default_factory=_now)
    messages: List[Dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["created_text"] = short_time(self.created_at)
        return data


@dataclass
class SessionInfo:
    """Serialisable view of a terminal session (owned by PtySession)."""

    id: str
    name: str
    kind: str
    pid: Optional[int]
    alive: bool
    cwd: str
    cols: int
    rows: int
    started_at: float
    last_activity: float
    exit_code: Optional[int]
    design_id: Optional[str] = None
    current_run_id: Optional[str] = None
    shell: str = "bash"

    @property
    def status(self) -> str:
        if self.alive:
            return "running" if self.current_run_id else "idle"
        return "exited"

    def as_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status
        data["started_text"] = short_time(self.started_at)
        data["last_activity_text"] = short_time(self.last_activity)
        data["elapsed"] = (_now() - self.started_at)
        data["elapsed_text"] = duration(data["elapsed"])
        return data
