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
import secrets
import signal
import struct
import termios
import threading
import time
from collections import deque
from typing import Any, Callable, Dict, List, Optional

import pyte

OSC_PREFIX = "\x1b]7770;owb;"
OSC_TOKEN_PLACEHOLDER = "%TOKEN%"
OSC_RE = re.compile(re.escape(OSC_PREFIX) + r"(.*?)(?:\x07|\x1b\\)", re.S)
RAW_LIMIT = 4 * 1024 * 1024
HISTORY_LINES = 4000

# Stages we recognise in terminal output.  This is a *detector*, not a source of
# truth: unknown stages are simply not claimed.
# OpenROAD-flow-scripts announces each step as
#     Running <script>.tcl, stage <N_stage>            (flow/scripts/flow.sh)
# where the script name is e.g. synth_odb / global_place / detail_route.  The
# earlier patterns required the stage word to follow "Running" directly, so
# "Running global_place.tcl" and "Running synth_odb.tcl" never matched -- which
# made the live stage panel a no-op on a real flow.
ORFS_RUN_RE = re.compile(r"Running\s+(\S+?)\.tcl,\s*stage\s+(\S+)", re.I)

ORFS_SCRIPT_STAGE = {
    "synth": "synth", "synth_odb": "synth", "synth_generic": "synth",
    "floorplan": "floorplan", "macro_place": "place", "tapcell": "place",
    "pdn": "place", "global_place_skip_io": "place", "global_place": "place",
    "detail_place": "place", "place": "place",
    "cts": "cts", "clock_tree": "cts",
    "grt": "grt", "global_route": "route", "detail_route": "route", "route": "route",
    "final_report": "finish", "finish": "finish",
}

STAGE_PATTERNS = [
    # "<stage dir>" forms such as 1_synth, 3_place, 6_final_report.
    (re.compile(r"\b\d+[_\-]?([a-z_]+)\b", re.I), 1),
    # Generic fallbacks for other flows / user scripts.
    (re.compile(r"\bstage\s*[=:]\s*([a-z_]+)", re.I), 1),
    (re.compile(r"\bRunning\s+(synth|floorplan|place|cts|grt|route|finish)\b", re.I), 1),
]

STAGE_ALIASES = {
    "synth": "synth", "synthesis": "synth", "1_synth": "synth",
    "floorplan": "floorplan", "2_floorplan": "floorplan",
    "place": "place", "placement": "place", "global_place": "place",
    "detail_place": "place", "macro_place": "place", "3_place": "place",
    "cts": "cts", "clock_tree_synthesis": "cts", "4_cts": "cts",
    "grt": "grt", "global_route": "route", "route": "route", "detail_route": "route",
    "5_route": "route", "5_1_grt": "route", "5_2_route": "route",
    "finish": "finish", "final_report": "finish", "6_final": "finish", "6_final_report": "finish",
}


def normalise_stage(token: str) -> Optional[str]:
    """Map a stage directory / script name onto the canonical stage list."""
    if not token:
        return None
    token = token.strip().lower().strip("/")
    if token in STAGE_ALIASES:
        return STAGE_ALIASES[token]
    if token in ORFS_SCRIPT_STAGE:
        return ORFS_SCRIPT_STAGE[token]
    # "3_place" / "2_1_floorplan" -> drop the numeric prefix and retry.
    stripped = re.sub(r"^\d+[_\-]*", "", token)
    if stripped in STAGE_ALIASES:
        return STAGE_ALIASES[stripped]
    if stripped in ORFS_SCRIPT_STAGE:
        return ORFS_SCRIPT_STAGE[stripped]
    for stage in STAGE_ORDER_NAMES:
        if stripped.startswith(stage):
            return stage
    return None


STAGE_ORDER_NAMES = ["synth", "floorplan", "place", "cts", "grt", "route", "finish"]


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
  printf '\033]7770;owb;%s;{"t":"prompt","ec":%d,"cwd":"%s","cmd":"%s"}\007' \
    "$OWB_OSC_TOKEN" "$ec" "$(__owb_esc "$PWD")" "$(__owb_esc "$line")"
  __owb_cmd=""
  __owb_armed=1
}

trap '__owb_preexec' DEBUG

# Guarantee bracketed paste: the workbench relies on it to insert a multi-line
# agent proposal WITHOUT the shell executing every line as it arrives.
bind 'set enable-bracketed-paste on' 2>/dev/null || true
bind 'set bell-style none' 2>/dev/null || true

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
  printf '\033]7770;owb;%s;{"t":"prompt","ec":%d,"cwd":"%s","cmd":"%s"}\007' \
    "$OWB_OSC_TOKEN" "$ec" "$(__owb_esc "$PWD")" "$(__owb_esc "${cmd# }")"
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
        self._in_escape = False    # inside a CSI/SS3 sequence
        self._closed = False
        self.command_seq = 0
        self.bracketed_paste = False
        # Unpredictable per-session value handed to the shell integration.  It
        # is a spoofing barrier, not a secret: the user's own processes could
        # read it, but ordinary output (logs, tool dumps) cannot.
        self.osc_token = secrets.token_hex(8)

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
        child_env["OWB_OSC_TOKEN"] = self.osc_token
        if env:
            child_env.update({k: str(v) for k, v in env.items()})

        shell = os.environ.get("SHELL") or "/bin/bash"
        if argv:
            args = list(argv)
            self.bracketed_paste = False
        else:
            base = os.path.basename(shell)
            self.shell = base
            if base.endswith("bash"):
                rc = shell_rc or os.path.expanduser("~/.openroad-workbench/shell/owb.bashrc")
                args = [shell, "--rcfile", rc, "-i"]
                self.bracketed_paste = True
            elif base.endswith("zsh"):
                rc = os.path.expanduser("~/.openroad-workbench/shell/owb.zshrc")
                child_env["ZDOTDIR"] = os.path.dirname(rc)
                args = [shell, "-i"]
                self.bracketed_paste = True
            else:
                args = [shell, "-i"]
                self.bracketed_paste = False

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
        # payload is "<token>;<json>" -- output from an arbitrary program cannot
        # guess the token, so it can no longer fabricate a Run.
        token, sep, body = payload.partition(";")
        if not sep or not self.osc_token or token != self.osc_token:
            self._emit("shell.prompt.rejected", reason="bad token")
            return
        try:
            data = json.loads(body)
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
        """Report every stage we can see in this chunk.

        The previous version returned after the first match *per chunk*, so when
        several stage lines arrived together (the normal case -- a flow prints
        them back to back) only one was recorded.
        """
        if not text or self._on_event is None:
            return
        seen: List[str] = []
        for line in text.splitlines():
            match = ORFS_RUN_RE.search(line)
            if match:
                stage = normalise_stage(match.group(2)) or normalise_stage(match.group(1))
                if stage and stage not in seen:
                    seen.append(stage)
                continue
            for pattern, group in STAGE_PATTERNS:
                found = pattern.search(line)
                if found:
                    stage = normalise_stage(found.group(group))
                    if stage and stage not in seen:
                        seen.append(stage)
                    break
        for stage in seen:
            self._emit("stage.observed", stage=stage)

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
        self._close_master()
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
            if self._in_escape:
                # Consume a CSI/SS3/function-key body: it ends at a letter or '~'.
                if char.isalpha() or char == "~":
                    self._in_escape = False
                continue
            if char == "\x1b":
                self._in_escape = True
                continue
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
            elif char.isprintable():
                self._line += char

    def write_raw(self, data: str) -> int:
        """Write to the PTY *without* treating it as typed keystrokes.

        Used to insert a proposal: the text is not a command the user typed, so
        it must not create an optimistic Run.
        """
        if not self.alive:
            raise RuntimeError("session %s is not running" % self.id)
        with self._lock:
            return os.write(self.master_fd, data.encode("utf-8", "replace"))

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

    def _row_text(self, row) -> str:
        """One screen row as text.

        The cell is a ``pyte.screens.Char`` namedtuple, so joining the cells
        themselves raises TypeError ("expected str instance, Char found").  That
        exception used to be swallowed by a bare ``except Exception: pass``,
        which is why scrollback silently returned nothing for every session.
        """
        return "".join(row[col].data for col in range(self._screen.columns))

    def _row_runs(self, row) -> List[Dict[str, Any]]:
        """One screen row as styled runs: [{'t': text, 'fg':..., 'b':...}, ...]."""
        runs: List[Dict[str, Any]] = []
        current: Optional[Dict[str, Any]] = None
        for col in range(self._screen.columns):
            cell = row[col]
            data = cell.data
            if not data:
                continue  # continuation cell of a double-width character
            key = (cell.fg, cell.bg, bool(cell.bold), bool(cell.italics),
                   bool(cell.underscore), bool(cell.reverse))
            if current is not None and current["_key"] == key:
                current["t"] += data
            else:
                current = {
                    "_key": key, "t": data, "fg": cell.fg, "bg": cell.bg,
                    "b": bool(cell.bold), "i": bool(cell.italics),
                    "u": bool(cell.underscore), "r": bool(cell.reverse),
                }
                runs.append(current)
        for run in runs:
            run.pop("_key", None)
        if runs:
            runs[-1]["t"] = runs[-1]["t"].rstrip()
            runs = [run for run in runs if run["t"]]
        return runs

    def _lines_and_runs(self, limit: Optional[int], with_runs: bool = True):
        with self._lock:
            display_rows = list(self._screen.buffer[row] for row in range(self._screen.lines))
            history_rows = list(self._screen.history.top)
        rows = history_rows + display_rows
        if limit:
            rows = rows[-limit:]
        texts = [self._row_text(row).rstrip() for row in rows]
        runs = [self._row_runs(row) for row in rows] if with_runs else [[] for _ in rows]
        return texts, runs

    def _all_lines(self) -> List[str]:
        texts, _ = self._lines_and_runs(None, with_runs=False)
        while len(texts) > 1 and not texts[-1]:
            texts.pop()
        return texts

    def screen_lines(self, limit: Optional[int] = None, include_history: bool = True) -> List[str]:
        texts, _ = self._lines_and_runs(None if include_history else self.rows, with_runs=False)
        while len(texts) > 1 and not texts[-1]:
            texts.pop()
        if limit:
            texts = texts[-limit:]
        return texts

    def screen_state(self, limit: int = 200, with_runs: bool = True) -> Dict[str, Any]:
        """Screen plus the metadata a client needs to place the cursor and to
        paint colour.  ``screen`` stays plain text so existing consumers keep
        working; ``runs`` carries the per-line styling."""
        texts, runs = self._lines_and_runs(limit)
        rows = self.rows
        while len(texts) > 1 and not texts[-1]:
            texts.pop()
            runs.pop()
        included_history = max(0, len(texts) - rows)
        state = {
            "screen": texts,
            "history_len": included_history,
            "history_lines": len(texts),
            "cursor": {"x": self._screen.cursor.x, "y": self._screen.cursor.y},
            "cols": self.cols,
            "rows": rows,
        }
        if with_runs:
            state["runs"] = runs
        return state

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

    def _close_master(self) -> None:
        """Exactly one code path may close the master fd.  Closing twice can
        silently close an unrelated fd that has since been reused."""
        with self._lock:
            fd, self.master_fd = self.master_fd, -1
        if fd is None or fd < 0:
            return
        try:
            os.close(fd)
        except OSError:
            pass

    def close(self) -> None:
        self.terminate(signal.SIGKILL)
        self._close_master()
