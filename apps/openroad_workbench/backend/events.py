from __future__ import annotations

"""Fan-out event bus.

The daemon produces events from two very different places:

* asyncio tasks (API calls, MCP polling), which may publish directly;
* the PTY reader **threads**, which must hop back onto the loop.

Both clients (TUI and Web) subscribe to the same stream, which is what makes
"TUI 和 Web 看到同一个 Session、Run、日志和状态" true rather than aspirational.
"""

import asyncio
import itertools
import threading
import time
from typing import Any, Dict, List, Optional


class EventBus:
    def __init__(self, loop: asyncio.AbstractEventLoop, replay: int = 400) -> None:
        self._loop = loop
        self._subs: List[asyncio.Queue] = []
        self._history: List[Dict[str, Any]] = []
        self._replay = replay
        self._seq = itertools.count(1)
        self._lock = threading.Lock()
        self._closed = False

    # ------------------------------------------------------------------ build
    def _build(self, type_: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"seq": next(self._seq), "ts": time.time(), "type": type_, "data": data}

    def _remember(self, event: Dict[str, Any]) -> None:
        with self._lock:
            self._history.append(event)
            if len(self._history) > self._replay:
                del self._history[: len(self._history) - self._replay]

    def _deliver(self, event: Dict[str, Any]) -> None:
        for queue in list(self._subs):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # A slow client must never stall the daemon.
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                except Exception:
                    pass

    # --------------------------------------------------------------- publish
    def publish(self, type_: str, **data: Any) -> Dict[str, Any]:
        """Publish from the event-loop thread."""
        event = self._build(type_, data)
        self._remember(event)
        self._deliver(event)
        return event

    def publish_threadsafe(self, type_: str, **data: Any) -> None:
        """Publish from a worker thread (PTY readers)."""
        event = self._build(type_, data)
        self._remember(event)
        if self._closed:
            return
        try:
            self._loop.call_soon_threadsafe(self._deliver, event)
        except RuntimeError:
            # Loop already closed during shutdown.
            pass

    # ------------------------------------------------------------- subscribe
    def subscribe(self, replay: bool = True) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=2000)
        if replay:
            with self._lock:
                history = list(self._history)
            for event in history:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    break
        self._subs.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        try:
            self._subs.remove(queue)
        except ValueError:
            pass

    def history(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._history)[-limit:]

    def close(self) -> None:
        self._closed = True
        self._subs.clear()
