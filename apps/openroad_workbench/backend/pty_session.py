from __future__ import annotations

"""A real PTY-backed terminal session.

Design notes
------------
* ``pty.fork()`` gives the child its own controlling terminal, so ``Ctrl-C``
  (``\\x03`` written to the master fd) is delivered by the kernel line
  discipline to the foreground process group.  We never synthesise signals for
  interactive interrupts – verified on the target host (exit status 130).
* A reader **thread** drains the master fd into three places: a bounded raw ring
  buffer (for log export / grep), a :mod:`pyte` screen (so remote clients need
  no terminal emulator of their own), and an event callback.
* Shell integration is installed through a generated rcfile that emits a private
  OSC sequence before every prompt.  That yields the *authoritative* command
  text, working directory and exit code of the previous command.  Keystroke
  reconstruction is used only as an optimistic placeholder so the UI can start a
  "Run" the moment the user presses Enter.
"""

import codecs
import errno
import fcntl
import json
import os
import pty
import re
import signal
import struct
import termios
import threading
import time
from collections import deque
from typing import Any, Callable, Dict, List, Optional

import pyte

OSC_PREFIX = "\x1b]7770;owb;"
OSC_RE = re.compile(re.escape(OSC_PREFIX) + r"(.*?)(?:\x07|\x1b\\)", re.S)
RAW_LIMIT = 4 * 1024 * 1024
HISTORY_LINES = 4000

# Stages we recognise in terminal output.  This is a *detector*, not a source of
# truth: unknown stages are simply not claimed.
STAGE_PATTERNS = [
    (re.compile(r"\bRunning\s+(synth|floorplan|place|cts|grt|route|finish)\b", re.I), 1),
    (re.compile(r"\b(?:ORFS|flow)\s*[:>]\s*(synth|floorplan|place|cts|grt|route|finish)\b", re.I), 1),
    (re.compile(r"^\s*\d+[_\-\s]?(synth|floorplan|place|cts|grt|route|finish)\b", re.I), 1),
    (re.compile(r"\b(?:stage|step)\s*[=:]\s*(synth|floorplan|place|cts|grt|route|finish)\b", re.I), 1),
]


def shell_integration_bashrc(path: str) -> str:
    """Write the generated bash rcfile and return its path."""
    body = r"""# OpenROAD Workbench shell integration -- generated, do not edit by hand.
# Sources the user's normal bashrc first so the environment is identical to a
# plain interactive shell, then adds a prompt hook used for run tracking.

if [ -n "${OWB_NO_USER_RC:-}" ]; then :; else
  [ -f "$HOME/.bashrc" ] && . "$HOME/.bashrc"
fi

__owb_esc() {
  local s=$1
  s=${s//\\/\\\\}
  s=${s//\"/\\\"}
  s=${s//$'\n'/ }
  s=${s//$'\r'/ }
  s=${s//$'\t'/ }
  printf '%s' "$s"
}

__owb_cmd=""
__owb_armed=0
__owb_ec=0
__owb_last=""

__owb_preexec() {
  case "$BASH_COMMAND" in
    __owb_*|*PROMPT_COMMAND*) return ;;
  esac
  [ "$__owb_armed" = "1" ] || return
  __owb_armed=0
  __owb_cmd="$BASH_COMMAND"
}

# Runs first in PROMPT_COMMAND: the only moment where $? still belongs to the
# user's command.  It also disarms the trap so other PROMPT_COMMAND entries
# (window-title printf and friends) can never be mistaken for user commands.
__owb_save_ec() {
  __owb_ec=$?
  __owb_armed=0
}

__owb_precmd() {
  local ec=$__owb_ec
  local line=""
  # `history 1` yields the whole command line, including compounds such as
  # "cd x && make" that a DEBUG trap would only partially capture.
  line="$(HISTTIMEFORMAT= builtin history 1 2>/dev/null)"
  line="${line#"${line%%[![:space:]]*}"}"
  line="${line#* }"
  line="${line#"${line%%[![:space:]]*}"}"
  # History suppression (ignoredups / ignorespace) can hide the command we just
  # ran; in that case fall back to what the DEBUG trap captured.
  if [ -z "$line" ]; then
    line="$__owb_cmd"
  elif [ -n "$__owb_cmd" ] && [ "$line" = "$__owb_last" ]; then
    line="$__owb_cmd"
  fi
  __owb_last="$line"
  printf '\033]7770;owb;{"t":"prompt","ec":%d,"cwd":"%s","cmd":"%s"}\007' \
    "$ec" "$(__owb_esc "$PWD")" "$(__owb_esc "$line")"
  __owb_cmd=""
  __owb_armed=1
}

trap '__owb_preexec' DEBUG

if declare -p PROMPT_COMMAND 2>/dev/null | grep -q 'declare -a'; then
  PROMPT_COMMAND=(__owb_save_ec "${PROMPT_COMMAND[@]}" __owb_precmd)
elif [ -n "$PROMPT_COMMAND" ]; then
  PROMPT_COMMAND="__owb_save_ec;$PROMPT_COMMAND;__owb_precmd"
else
  PROMPT_COMMAND="__owb_save_ec;__owb_precmd"
fi
"""
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)
    return path


def shell_integration_zshrc(path: str) -> str:
    body = r"""# OpenROAD Workbench shell integration for zsh -- generated.
[ -f "$HOME/.zshrc" ] && . "$HOME/.zshrc"
__owb_esc() {
  local s=$1
  s=${s//\\/\\\\}
  s=${s//\"/\\\"}
  s=${s//$'\n'/ }
  printf '%s' "$s"
}
__owb_ec=0
__owb_save_ec() { __owb_ec=$?; }
__owb_precmd() {
  local ec=$__owb_ec
  local cmd="$(fc -ln -1 2>/dev/null)"
  printf '\033]7770;owb;{"t":"prompt","ec":%d,"cwd":"%s","cmd":"%s"}\007' \
    "$ec" "$(__owb_esc "$PWD")" "$(__owb_esc "${cmd# }")"
  __owb_ec=0
}
if [ -n "${precmd_functions+x}" ]; then
  precmd_functions=(__owb_save_ec $precmd_functions __owb_precmd)
else
  precmd_functions=(__owb_save_ec __owb_precmd)
fi
"""
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)
    return path


class PtySession:
    """One interactive terminal window backed by a real PTY."""

    def __init__(
        self,
        session_id: str,
        name: str,
        cwd: str,
        argv: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        cols: int = 120,
        rows: int = 32,
        kind: str = "shell",
        design_id: Optional[str] = None,
        on_event: Optional[Callable[..., None]] = None,
        shell_rc: Optional[str] = None,
    ) -> None:
        self.id = session_id
        self.name = name
        self.kind = kind
        self.design_id = design_id
        self.cols = cols
        self.rows = rows
        self.started_at = time.time()
        self.last_activity = self.started_at
        self.exit_code: Optional[int] = None
        self.alive = False
        self.shell = "bash"
        self._on_event = on_event
        self._lock = threading.RLock()
        self._raw: deque = deque()
        self._raw_size = 0
        self._screen = pyte.HistoryScreen(cols, rows, history=HISTORY_LINES, ratio=0.5)
        self._stream = pyte.Stream(self._screen)
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._osc_tail = ""
        self._version = 0
        self._reader: Optional[threading.Thread] = None
        self._line = ""            # optimistic keystroke reconstruction
        self._closed = False
        self.command_seq = 0

        self._spawn(argv, cwd, env, shell_rc)

    # ------------------------------------------------------------------ spawn
    def _spawn(
        self,
        argv: Optional[List[str]],
        cwd: str,
        env: Optional[Dict[str, str]],
        shell_rc: Optional[str],
    ) -> None:
        child_env = dict(os.environ)
        child_env.setdefault("TERM", "xterm-256color")
        child_env["OWB_SESSION"] = self.id
        child_env["OWB_SESSION_NAME"] = self.name
        if env:
            child_env.update({k: str(v) for k, v in env.items()})

        shell = os.environ.get("SHELL") or "/bin/bash"
        if argv:
            args = list(argv)
        else:
            base = os.path.basename(shell)
            self.shell = base
            if base.endswith("bash"):
                rc = shell_rc or os.path.expanduser("~/.openroad-workbench/shell/owb.bashrc")
                args = [shell, "--rcfile", rc, "-i"]
            elif base.endswith("zsh"):
                rc = os.path.expanduser("~/.openroad-workbench/shell/owb.zshrc")
                child_env["ZDOTDIR"] = os.path.dirname(rc)
                args = [shell, "-i"]
            else:
                args = [shell, "-i"]

        pid, fd = pty.fork()
        if pid == 0:  # pragma: no cover - child process
            try:
                os.chdir(cwd)
            except OSError:
                os.chdir(os.path.expanduser("~"))
            try:
                os.execvpe(args[0], args, child_env)
            except Exception as exc:  # pragma: no cover
                os.write(2, ("openroad-workbench: cannot start %s: %s\n" % (args[0], exc)).encode())
                os._exit(127)

        self.pid = pid
        self.master_fd = fd
        self.alive = True
        self._apply_winsize()
        self._reader = threading.Thread(target=self._read_loop, name="pty-reader-%s" % self.id, daemon=True)
        self._reader.start()
        self._emit("session.started", session=self.snapshot(include_screen=False))

    def _apply_winsize(self) -> None:
        try:
            fcntl.ioctl(
                self.master_fd,
                termios.TIOCSWINSZ,
                struct.pack("HHHH", self.rows, self.cols, 0, 0),
            )
        except OSError:
            pass

    # ------------------------------------------------------------------ events
    def _emit(self, type_: str, **data: Any) -> None:
        if self._on_event is None:
            return
        try:
            self._on_event(type_, session_id=self.id, **data)
        except Exception:
            pass

    # ------------------------------------------------------------------ reader
    def _read_loop(self) -> None:
        while True:
            try:
                chunk = os.read(self.master_fd, 65536)
            except OSError as exc:
                if exc.errno in (errno.EIO, errno.EBADF):
                    break
                if exc.errno == errno.EINTR:
                    continue
                break
            if not chunk:
                break
            self._ingest(chunk)
        self._finalise()

    def _ingest(self, chunk: bytes) -> None:
        with self._lock:
            self._raw.append(chunk)
            self._raw_size += len(chunk)
            while self._raw_size > RAW_LIMIT and len(self._raw) > 1:
                self._raw_size -= len(self._raw.popleft())
            self.last_activity = time.time()
            self._version += 1

        text = self._decoder.decode(chunk)
        clean, payloads = self._split_osc(text)
        if clean:
            try:
                self._stream.feed(clean)
            except Exception:
                pass
        self._detect_stages(clean)
        self._emit("terminal.output", bytes=len(chunk), text=clean[-8000:])
        for payload in payloads:
            self._handle_osc(payload)

    def _split_osc(self, text: str):
        if not text:
            return "", []
        buffer = self._osc_tail + text
        self._osc_tail = ""
        out: List[str] = []
        payloads: List[str] = []
        pos = 0
        while True:
            start = buffer.find(OSC_PREFIX, pos)
            if start == -1:
                out.append(buffer[pos:])
                break
            out.append(buffer[pos:start])
            bel = buffer.find("\x07", start)
            st = buffer.find("\x1b\\", start)
            ends = [e for e in (bel, st) if e != -1]
            if not ends:
                # Sequence (and possibly its payload) continues in the next chunk.
                self._osc_tail = buffer[start:]
                break
            end = min(ends)
            payloads.append(buffer[start + len(OSC_PREFIX):end])
            pos = end + (1 if buffer[end] == "\x07" else 2)
        return "".join(out), payloads

    def _handle_osc(self, payload: str) -> None:
        try:
            data = json.loads(payload)
        except Exception:
            return
        if data.get("t") != "prompt":
            return
        cwd = data.get("cwd") or self.cwd
        command = (data.get("cmd") or "").strip()
        exit_code = data.get("ec")
        self.cwd_hint = cwd
        self.exit_code = exit_code
        self._emit(
            "shell.prompt",
            cwd=cwd,
            command=command,
            exit_code=exit_code,
        )

    def _detect_stages(self, text: str) -> None:
        if not text or self._on_event is None:
            return
        for line in text.splitlines():
            for pattern, group in STAGE_PATTERNS:
                match = pattern.search(line)
                if match:
                    self._emit("stage.observed", stage=match.group(group).lower())
                    return

    def _finalise(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        status = None
        try:
            _, raw = os.waitpid(self.pid, 0)
            status = os.waitstatus_to_exitcode(raw)
        except ChildProcessError:
            status = None
        except OSError:
            status = None
        self.exit_code = status
        self.alive = False
        try:
            os.close(self.master_fd)
        except OSError:
            pass
        self._emit("session.exited", exit_code=status, session=self.snapshot(include_screen=False))

    # ------------------------------------------------------------------- input
    def write(self, data: str) -> int:
        """Write raw bytes to the PTY (keystrokes, not lines)."""
        if not self.alive:
            raise RuntimeError("session %s is not running" % self.id)
        raw = data.encode("utf-8", "replace")
        with self._lock:
            written = os.write(self.master_fd, raw)
        self._track_input(data)
        return written

    def _track_input(self, data: str) -> None:
        for char in data:
            if char == "\r" or char == "\n":
                command = self._line.strip()
                self._line = ""
                if command:
                    with self._lock:
                        self.command_seq += 1
                        seq = self.command_seq
                    self._emit("command.submitted", command=command, seq=seq)
            elif char in ("\x7f", "\x08"):
                self._line = self._line[:-1]
            elif char in ("\x03", "\x15"):
                self._line = ""
            elif char == "\x1b":
                # Arrow keys / escapes: drop the pending guess, do not clear history.
                self._line = self._line
            elif char.isprintable():
                self._line += char

    def interrupt(self) -> None:
        if self.alive:
            try:
                os.write(self.master_fd, b"\x03")
            except OSError:
                pass

    def terminate(self, sig: int = signal.SIGTERM) -> None:
        if not self.alive:
            return
        try:
            os.killpg(os.getpgid(self.pid), sig)
        except OSError:
            try:
                os.kill(self.pid, sig)
            except OSError:
                pass

    def resize(self, cols: int, rows: int) -> None:
        self.cols = max(20, int(cols))
        self.rows = max(5, int(rows))
        self._apply_winsize()

    # ------------------------------------------------------------------- views
    @property
    def version(self) -> int:
        return self._version

    @property
    def cwd(self) -> str:
        candidate = getattr(self, "cwd_hint", None)
        if candidate and os.path.isdir(candidate):
            return candidate
        try:
            return os.readlink("/proc/%d/cwd" % self.pid)
        except OSError:
            return candidate or os.path.expanduser("~")

    def _all_lines(self) -> List[str]:
        """Full buffer: scrollback history followed by the visible screen."""
        with self._lock:
            lines = list(self._screen.display)
            try:
                width = self._screen.columns
                lines = [
                    "".join(line[col] for col in range(width))
                    for line in self._screen.history.top
                ] + lines
            except Exception:
                pass
        return [line.rstrip() for line in lines]

    def screen_lines(self, limit: Optional[int] = None, include_history: bool = True) -> List[str]:
        lines = self._all_lines()
        if not include_history:
            lines = lines[-self.rows:]
        # Trim trailing blank lines, keeping at least one.
        while len(lines) > 1 and not lines[-1]:
            lines.pop()
        if limit:
            lines = lines[-limit:]
        return lines

    def screen_state(self, limit: int = 200) -> Dict[str, Any]:
        """Screen plus the metadata a client needs to place the cursor."""
        lines = self._all_lines()
        total = len(lines)
        trimmed = lines[-limit:] if limit and total > limit else list(lines)
        included_history = max(0, len(trimmed) - self.rows)
        while len(trimmed) > 1 and not trimmed[-1]:
            trimmed.pop()
        return {
            "screen": trimmed,
            "history_len": included_history,
            "cursor": {"x": self._screen.cursor.x, "y": self._screen.cursor.y},
            "cols": self.cols,
            "rows": self.rows,
        }

    def raw_text(self) -> str:
        with self._lock:
            return b"".join(self._raw).decode("utf-8", "replace")

    def snapshot(self, include_screen: bool = True, screen_lines: int = 200) -> Dict[str, Any]:
        data = {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "pid": self.pid,
            "alive": self.alive,
            "cwd": self.cwd,
            "cols": self.cols,
            "rows": self.rows,
            "started_at": self.started_at,
            "last_activity": self.last_activity,
            "exit_code": self.exit_code,
            "design_id": self.design_id,
            "shell": self.shell,
            "version": self._version,
            "status": ("running" if self.alive else "exited"),
        }
        if include_screen:
            state = self.screen_state(limit=screen_lines)
            data["screen"] = state["screen"]
            data["history_len"] = state["history_len"]
            data["cursor"] = state["cursor"]
        return data

    def close(self) -> None:
        self.terminate(signal.SIGKILL)
        try:
            os.close(self.master_fd)
        except OSError:
            pass
