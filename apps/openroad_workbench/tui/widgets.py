from __future__ import annotations

"""TUI widgets: the real terminal pane, the agent pane and the status surfaces."""

from typing import Any, Callable, Dict, List, Optional

from rich.markup import escape
from rich.text import Text
from textual import events
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.containers import VerticalScroll
from textual.widgets import Input, Static

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
        self.runs: List[List[Dict[str, Any]]] = []
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
        self.runs = frame.get("runs") or []
        self.cursor = frame.get("cursor") or {"x": 0, "y": 0}
        self.history_len = int(frame.get("history_len") or 0)
        self.pty_rows = int(frame.get("rows") or 32)
        self.session_id = frame.get("id") or self.session_id
        self.session_name = frame.get("name") or self.session_name
        self.refresh()

    # ------------------------------------------------------------- rendering
    # pyte colour name -> rich colour name
    COLORS = {
        "default": None, "black": "black", "red": "red", "green": "green",
        "brown": "yellow", "blue": "blue", "magenta": "magenta", "cyan": "cyan",
        "white": "white", "brightblack": "bright_black", "brightred": "bright_red",
        "brightgreen": "bright_green", "brightbrown": "bright_yellow",
        "brightblue": "bright_blue", "brightmagenta": "bright_magenta",
        "brightcyan": "bright_cyan", "brightwhite": "bright_white",
    }

    def _run_style(self, run: Dict[str, Any]) -> str:
        parts: List[str] = []
        fg = self.COLORS.get(run.get("fg") or "default")
        bg = self.COLORS.get(run.get("bg") or "default")
        if fg:
            parts.append(fg)
        if bg:
            parts.append("on " + bg)
        if run.get("b"):
            parts.append("bold")
        if run.get("i"):
            parts.append("italic")
        if run.get("u"):
            parts.append("underline")
        if run.get("r"):
            parts.append("reverse")
        return " ".join(parts)

    def _line_text(self, index: int, width: int) -> Text:
        """Build one styled line, falling back to plain text for old frames."""
        line = Text(no_wrap=True, overflow="crop")
        runs = self.runs[index] if index < len(self.runs) else []
        if not runs:
            line.append((self.lines[index] if index < len(self.lines) else "")[:width])
            return line
        cursor_col = -1
        cursor_row = self.history_len + int(self.cursor.get("y", 0))
        if index == cursor_row:
            cursor_col = int(self.cursor.get("x", 0))
        column = 0
        for run in runs:
            text = run.get("t") or ""
            style = self._run_style(run)
            if cursor_col < 0 or not (column <= cursor_col < column + len(text)):
                line.append(text, style=style)
            else:
                cut = cursor_col - column
                line.append(text[:cut], style=style)
                line.append(text[cut], style=(style + " reverse").strip())
                line.append(text[cut + 1:], style=style)
            column += len(text)
            if column >= width:
                break
        return line

    def render(self) -> Text:
        height = max(1, self.size.height)
        width = max(20, self.size.width)
        total = len(self.lines)
        end = max(1, total - self.scroll_back_lines)
        start = max(0, end - height)
        out = Text(no_wrap=True, overflow="crop")
        for offset, index in enumerate(range(start, end)):
            if offset:
                out.append("\n")
            out.append_text(self._line_text(index, width))
        return out

    # -------------------------------------------------------------- input out
    # Keys the application owns.  Everything else is forwarded to the PTY, so the
    # terminal keeps Ctrl-U (kill line), Ctrl-D (EOF), Ctrl-B/E (cursor moves)
    # and the whole readline keymap -- stealing those is what makes a "terminal
    # replacement" worse than a terminal.
    APP_KEYS = {
        "ctrl+n", "ctrl+w", "ctrl+q", "ctrl+g",
        "alt+u", "alt+d", "alt+b",
        "f1", "f2", "f3", "f4",
    }

    def on_key(self, event: events.Key) -> None:
        if event.key in self.APP_KEYS:
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

    # Colours are applied as Text styles, never through markup: command text is
    # user data and "[" appears in it constantly (printf, awk, globs), which used
    # to raise MarkupError and kill the whole TUI.
    STATUS_COLOR = {
        "running": "yellow", "idle": "yellow", "exited": "red",
        "success": "green", "failed": "red", "cancelled": "magenta",
    }

    def update_sessions(self, sessions: List[Dict[str, Any]], active: Optional[str]) -> None:
        text = Text()
        for index, session in enumerate(sessions[:9], start=1):
            if index > 1:
                text.append("\n")
            marker = "▸" if session["id"] == active else " "
            state = session.get("status", "?")
            text.append("%s %d %s  " % (marker, index, session.get("name", session["id"])))
            text.append("[%s]" % state, style=self.STATUS_COLOR.get(state, "white"))
        if not sessions:
            text.append("(无终端)")
        self.sessions_view.update(text)

    def update_runs(self, runs: List[Dict[str, Any]]) -> None:
        text = Text()
        for index, run in enumerate(runs[:12]):
            if index:
                text.append("\n")
            status = run.get("status", "?")
            text.append("[%s]" % status[:4], style=self.STATUS_COLOR.get(status, "white"))
            text.append(" %s %s" % (run.get("started_text", ""), (run.get("command") or "")[:22]))
        if not runs:
            text.append("(暂无运行记录)")
        self.runs_view.update(text)


class AgentPane(Vertical):
    """Agent transcript + input.

    Messages are built as ``rich.text.Text`` objects rather than markup strings:
    agent replies, command text and error messages are user data, and parsing
    them as markup both mangles them and can raise MarkupError (which killed the
    whole application).
    """

    DEFAULT_CSS = """
    AgentPane {
        width: 52;
        border-left: solid $panel;
    }
    AgentPane #agent-scroll { height: 1fr; }
    AgentPane Input { dock: bottom; }
    AgentPane .agent-msg { padding: 0 1; }
    """

    KIND_STYLE = {
        "user": "bold cyan", "bot": "green", "ok": "green",
        "warn": "yellow", "error": "bold red", "help": "", "info": "",
    }

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.scroll = VerticalScroll(id="agent-scroll")
        self.prompt = Input(placeholder="问 Agent：写个 Tcl/Python 脚本…", id="agent-input")
        self.messages: List[str] = []

    def compose(self):
        yield Static(Text("Agent  (F2 聚焦 · Esc 回到终端)", style="bold"), classes="section")
        yield self.scroll
        yield self.prompt

    def write_line(self, text: str, kind: str = "bot") -> None:
        self.messages.append(text)
        body = Text(text)
        body.stylize(self.KIND_STYLE.get(kind, ""))
        widget = Static(body, classes="agent-msg")
        self.scroll.mount(widget)
        self.scroll.scroll_end(animate=False, immediate=True)

    def write_user(self, text: str) -> None:
        self.write_line(text, kind="user")

    def clear_log(self) -> None:
        self.messages = []
        for child in list(self.scroll.children):
            child.remove()
