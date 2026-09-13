from __future__ import annotations

"""TUI widgets: the real terminal pane, the agent pane and the status surfaces."""

from typing import Any, Callable, Dict, List, Optional

from rich.text import Text
from textual import events
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Input, RichLog, Static

# --------------------------------------------------------------------- keymap
SPECIAL_KEYS = {
    "enter": "\r",
    "return": "\r",
    "backspace": "\x7f",
    "tab": "\t",
    "shift+tab": "\x1b[Z",
    "escape": "\x1b",
    "up": "\x1b[A",
    "down": "\x1b[B",
    "right": "\x1b[C",
    "left": "\x1b[D",
    "home": "\x1b[H",
    "end": "\x1b[F",
    "insert": "\x1b[2~",
    "delete": "\x1b[3~",
    "pageup": "\x1b[5~",
    "pagedown": "\x1b[6~",
    "f1": "\x1bOP",
    "f2": "\x1bOQ",
    "f3": "\x1bOR",
    "f4": "\x1bOS",
    "f5": "\x1b[15~",
    "f6": "\x1b[17~",
    "f7": "\x1b[18~",
    "f8": "\x1b[19~",
    "f9": "\x1b[20~",
    "f10": "\x1b[21~",
    "f11": "\x1b[23~",
    "f12": "\x1b[24~",
    "space": " ",
}

CTRL_SPECIAL = {
    "ctrl+space": "\x00",
    "ctrl+@": "\x00",
    "ctrl+\\": "\x1c",
    "ctrl+]": "\x1d",
    "ctrl+^": "\x1e",
    "ctrl+_": "\x1f",
    "ctrl+/": "\x1f",
    "ctrl+[": "\x1b",
}


def key_to_data(event: events.Key) -> Optional[str]:
    """Translate a Textual key event into the bytes a PTY expects."""
    key = event.key or ""
    if key in SPECIAL_KEYS:
        return SPECIAL_KEYS[key]
    if key in CTRL_SPECIAL:
        return CTRL_SPECIAL[key]
    if key.startswith("ctrl+") and len(key) == 6 and "a" <= key[5] <= "z":
        return chr(ord(key[5]) - 96)
    if key.startswith("alt+") and len(key) == 5:
        return "\x1b" + key[4]
    if event.is_printable and event.character:
        return event.character
    return None


class TerminalPane(Widget):
    """Renders the daemon-side terminal screen; forwards keystrokes back."""

    can_focus = True
    DEFAULT_CSS = """
    TerminalPane {
        height: 1fr;
        width: 1fr;
        padding: 0 0 0 1;
    }
    """

    def __init__(self, on_input: Optional[Callable[[str], None]] = None,
                 on_resize: Optional[Callable[[int, int], None]] = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.lines: List[str] = []
        self.cursor = {"x": 0, "y": 0}
        self.history_len = 0
        self.pty_rows = 32
        self.scroll_back_lines = 0
        self.session_id: Optional[str] = None
        self.session_name = ""
        self._on_input = on_input
        self._on_resize = on_resize

    # ------------------------------------------------------------- data in
    def set_frame(self, frame: Dict[str, Any]) -> None:
        self.lines = frame.get("screen") or []
        self.cursor = frame.get("cursor") or {"x": 0, "y": 0}
        self.history_len = int(frame.get("history_len") or 0)
        self.pty_rows = int(frame.get("rows") or 32)
        self.session_id = frame.get("id") or self.session_id
        self.session_name = frame.get("name") or self.session_name
        self.refresh()

    # ------------------------------------------------------------- rendering
    def render(self) -> Text:
        height = max(1, self.size.height)
        width = max(20, self.size.width)
        total = len(self.lines)
        end = max(1, total - self.scroll_back_lines)
        start = max(0, end - height)
        window = self.lines[start:end]
        cursor_abs_y = self.history_len + int(self.cursor.get("y", 0))
        cursor_x = int(self.cursor.get("x", 0))

        text = Text(no_wrap=True, overflow="crop")
        for index, line in enumerate(window):
            if index:
                text.append("\n")
            absolute = start + index
            if absolute == cursor_abs_y and 0 <= cursor_x < max(len(line), 1):
                clipped = line[:width]
                if cursor_x < len(clipped):
                    text.append(clipped[:cursor_x], style="")
                    text.append(clipped[cursor_x], style="reverse")
                    text.append(clipped[cursor_x + 1:], style="")
                else:
                    text.append(clipped + " " * (cursor_x - len(clipped)), style="")
                    text.append(" ", style="reverse")
            else:
                text.append(line[:width], style="")
        return text

    # -------------------------------------------------------------- input out
    def on_key(self, event: events.Key) -> None:
        if event.key in ("ctrl+b", "ctrl+j", "ctrl+n", "ctrl+w", "ctrl+q", "f1"):
            return  # let the app bindings handle these
        data = key_to_data(event)
        if data is None:
            return
        event.stop()
        event.prevent_default()
        if self.scroll_back_lines:
            self.scroll_back_lines = 0
        if self._on_input is not None:
            self._on_input(data)

    def on_resize(self, event: events.Resize) -> None:
        if self._on_resize is not None:
            self._on_resize(max(20, self.size.width), max(5, self.size.height))
        self.refresh()

    # ------------------------------------------------------------- scrolling
    def scroll_back(self, lines: int) -> None:
        self.scroll_back_lines = min(max(0, self.scroll_back_lines + lines), max(0, len(self.lines) - 1))
        self.refresh()

    def scroll_to_bottom(self) -> None:
        self.scroll_back_lines = 0
        self.refresh()

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        self.scroll_back(3)

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        self.scroll_back(-3)


class StatusBar(Static):
    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        background: $panel;
        color: $text;
        padding: 0 1;
    }
    """


class SessionList(Static):
    DEFAULT_CSS = """
    SessionList {
        height: auto;
        padding: 0 1;
    }
    """


class RunList(Static):
    DEFAULT_CSS = """
    RunList {
        height: 1fr;
        padding: 0 1;
    }
    """


class Sidebar(Vertical):
    DEFAULT_CSS = """
    Sidebar {
        width: 34;
        border-right: solid $panel;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.sessions_view = SessionList(id="session-list")
        self.runs_view = RunList(id="run-list")

    def compose(self):
        yield Static("[b]终端[/b]", classes="section")
        yield self.sessions_view
        yield Static("[b]最近运行[/b]", classes="section")
        yield self.runs_view

    def update_sessions(self, sessions: List[Dict[str, Any]], active: Optional[str]) -> None:
        lines: List[str] = []
        for index, session in enumerate(sessions[:9], start=1):
            marker = "▸" if session["id"] == active else " "
            state = session.get("status", "?")
            colour = {"running": "green", "idle": "yellow", "exited": "red"}.get(state, "white")
            lines.append("%s %d %s  [%s]%s" % (
                marker, index, session.get("name", session["id"]), colour, state))
        if not lines:
            lines.append("(无终端)")
        self.sessions_view.update("\n".join(lines))

    def update_runs(self, runs: List[Dict[str, Any]]) -> None:
        lines: List[str] = []
        for run in runs[:12]:
            status = run.get("status", "?")
            colour = {"success": "green", "failed": "red", "running": "yellow",
                      "cancelled": "magenta"}.get(status, "white")
            command = (run.get("command") or "")[:22]
            lines.append("[%s]%s[/] %s %s" % (colour, status[:4], run.get("started_text", ""), command))
        if not lines:
            lines.append("(暂无运行记录)")
        self.runs_view.update("\n".join(lines))


class AgentPane(Vertical):
    DEFAULT_CSS = """
    AgentPane {
        width: 46;
        border-left: solid $panel;
    }
    AgentPane RichLog { height: 1fr; }
    AgentPane Input { dock: bottom; }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.transcript = RichLog(highlight=False, markup=True, wrap=True, id="agent-log")
        self.prompt = Input(placeholder="问 Agent：写个 Tcl/Python 脚本…", id="agent-input")

    def compose(self):
        yield Static("[b]Agent[/b]  (Ctrl+J 聚焦 · Esc 回到终端)", classes="section")
        yield self.transcript
        yield self.prompt

    def write_line(self, text: str) -> None:
        self.transcript.write(text)

    def clear_log(self) -> None:
        self.transcript.clear()
