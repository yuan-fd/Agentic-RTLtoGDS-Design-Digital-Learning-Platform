#!/usr/bin/env python3
"""Terminal-only client for the durable L1 Workbench API.

The left pane is a projection of durable L1 facts: visible decisions, Policy,
typed tool use, Runtime transitions and evidence. It deliberately does not
render hidden reasoning, provider transcripts, commands, secrets, or paths.
The right pane is the human client. No state here is authoritative; its event
list is only a cursor cache.
"""
from __future__ import annotations

import argparse
import curses
import json
import textwrap
import time
from urllib.parse import quote
from urllib.request import Request, urlopen


class Client:
    def __init__(self, base: str): self.base = base.rstrip("/")
    def post(self, path: str, payload: dict) -> dict:
        request = Request(self.base + path, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        return json.loads(urlopen(request, timeout=10).read())
    def get(self, path: str) -> dict:
        return json.loads(urlopen(self.base + path, timeout=10).read())


def _wrap(value: object, width: int) -> list[str]:
    return [line for part in str(value or "").splitlines() or [""] for line in textwrap.wrap(part, width=max(12, width))] or [""]


class Dashboard:
    COMMANDS = (":new <goal>", ":answer <answer>", ":run [decision summary]", ":cancel [reason]", ":recover   :refresh   :quit")

    def __init__(self, client: Client):
        self.client, self.sid, self.after, self.events = client, None, -1, []
        self.notice, self.connection, self.input_buffer, self.last_refresh = "Ready. Create a durable session with :new <natural-language goal>.", "not contacted", "", 0.0

    def refresh(self) -> None:
        if not self.sid: return
        data = self.client.get(f"/api/l1/sessions/{quote(self.sid)}/events?after={self.after}")
        incoming = data.get("events", [])
        if incoming:
            self.events.extend(incoming); self.after = max(event["sequence"] for event in self.events)
        self.connection, self.last_refresh = "connected", time.monotonic()

    def _need_session(self) -> None:
        if not self.sid: raise ValueError("Create a Session first: :new <goal>")

    def command(self, text: str) -> None:
        try:
            op, _, argument = text[1:].partition(" ")
            if op == "new":
                if not argument.strip(): raise ValueError("Usage: :new <natural-language goal>")
                result = self.client.post("/api/l1/sessions", {"text": argument})
                self.sid, self.after, self.events = result["session_id"], -1, []
                self.notice = f"Session created: {result['status']}. Review clarification in Client."; self.refresh()
            elif op == "answer":
                self._need_session()
                self.client.post(f"/api/l1/sessions/{self.sid}/answers", {"answers": [{"question_id": "objective-1", "field": "objective", "value": argument}]})
                self.notice = "Clarification persisted; Goal IR is frozen."; self.refresh()
            elif op == "run":
                self._need_session()
                result = self.client.post(f"/api/l1/sessions/{self.sid}/execute", {"decision_summary": argument or "Execute one bounded typed Runtime tool."})
                self.notice = f"Runtime recorded: {result['runtime']['run']['status']}."; self.refresh()
            elif op == "cancel":
                self._need_session(); self.client.post(f"/api/l1/sessions/{self.sid}/cancel", {"reason": argument or "operator cancellation"})
                self.notice = "Cancellation requested through Runtime authority."; self.refresh()
            elif op == "recover":
                self._need_session(); self.client.post(f"/api/l1/sessions/{self.sid}/recover", {})
                self.notice = "Durable Session recovery requested (no duplicate Runtime submission)."; self.refresh()
            elif op == "refresh":
                self.refresh(); self.notice = "Fetched new durable events by cursor."
            else: self.notice = "Commands: " + " | ".join(self.COMMANDS)
        except Exception as exc:
            self.connection, self.notice = "error", f"API error: {exc}"

    def _phase(self) -> str:
        kinds = {event.get("kind") for event in self.events}
        if "state_transition" in kinds:
            terminal = next((event.get("facts", {}).get("terminal_status") for event in reversed(self.events) if event.get("kind") == "state_transition"), None)
            return f"RUNTIME {str(terminal or 'recorded').upper()}"
        if "tool_receipt" in kinds: return "RUNTIME RECEIPT RECORDED"
        if "policy_decided" in kinds: return "POLICY DECIDED"
        if "goal_finalized" in kinds: return "GOAL FROZEN / READY TO PLAN"
        if "goal_drafted" in kinds: return "WAITING FOR CLARIFICATION"
        return "WAITING FOR USER GOAL"

    def _harness_rows(self) -> list[str]:
        if not self.events:
            return ["[1] Goal draft       waiting for user request", "[2] Frozen Goal IR   created after typed clarification", "[3] Visible plan     structured decision summary", "[4] Policy verdict   ALLOW / DENY / NEEDS_CLARIFICATION", "[5] Typed tool call  validated before Runtime", "[6] Runtime receipt  exit status + artifact references", "[7] State transition durable terminal evidence", "", "This panel shows observable decisions, not hidden model reasoning."]
        labels = {"goal_drafted": "GOAL DRAFT", "goal_finalized": "FROZEN GOAL IR", "tool_called": "TYPED TOOL / PLAN", "policy_decided": "POLICY", "tool_receipt": "RUNTIME RECEIPT", "state_transition": "RUNTIME STATE", "stopped": "LOOP STOPPED"}
        rows = []
        for event in self.events[-16:]:
            kind, facts = event.get("kind", "event"), event.get("facts") or {}
            if kind == "goal_drafted": detail = "clarification requested"
            elif kind == "goal_finalized": detail = f"objective={(facts.get('goal_ir') or {}).get('objective') or 'recorded'}"
            elif kind == "tool_called": detail = event.get("planner_summary") or "structured decision persisted"
            elif kind == "policy_decided": detail = f"verdict={event.get('policy_verdict') or facts.get('verdict') or 'recorded'}"
            elif kind == "tool_receipt":
                result = facts.get("result") or {}
                detail = f"status={facts.get('status') or 'accepted'}; run_id={result.get('run_id') or 'recorded'}"
            elif kind == "state_transition": detail = f"terminal_status={facts.get('terminal_status') or facts.get('status') or 'recorded'}"
            else: detail = event.get("planner_summary") or "durable event recorded"
            rows.extend([f"#{event.get('sequence', '?'):>3} {labels.get(kind, kind)}", f"      {detail}"])
        return rows

    def _client_rows(self) -> list[str]:
        rows = ["You control the durable L1 Session here.", "Natural language becomes typed Goal IR; never shell text.", "", "Start:", "  :new Optimize this bounded flow", "Then answer clarification:", "  :answer <objective>", "Then permit visible bounded action:", "  :run <decision summary>", "", "Session", f"  id: {self.sid or 'none'}", f"  phase: {self._phase()}", f"  event cursor: {self.after}", "", "Controls"]
        rows.extend(f"  {command}" for command in self.COMMANDS)
        draft = next((e for e in reversed(self.events) if e.get("kind") == "goal_drafted"), None)
        if draft and (draft.get("facts") or {}).get("blocking_fields"):
            question = next(iter((draft.get("facts") or {}).get("clarification_questions") or []), {})
            rows.extend(["", "Clarification pending", f"  {question.get('prompt', 'Answer with :answer <objective>')}", "  Reply: :answer <objective>"])
        return rows

    @staticmethod
    def _put(win, y: int, x: int, value: str, width: int, attrs: int = 0) -> None:
        try:
            if y >= 0 and x >= 0 and width > 0: win.addnstr(y, x, value, width, attrs)
        except curses.error: pass

    def _panel(self, win, title: str, x: int, y: int, width: int, height: int, rows: list[str]) -> None:
        if width < 16 or height < 4: return
        try:
            win.addnstr(y, x + 2, f" {title} ", width - 4, curses.A_BOLD)
            win.vline(y + 1, x, curses.ACS_VLINE, height - 1); win.vline(y + 1, x + width - 1, curses.ACS_VLINE, height - 1)
            win.hline(y + height - 1, x, curses.ACS_HLINE, width); win.addch(y + height - 1, x, curses.ACS_LLCORNER); win.addch(y + height - 1, x + width - 1, curses.ACS_LRCORNER)
        except curses.error: return
        row = y + 1
        for value in rows:
            for line in _wrap(value, width - 4):
                if row >= y + height - 1: return
                self._put(win, row, x + 2, line, width - 4); row += 1

    def draw(self, win) -> None:
        win.erase(); height, width = win.getmaxyx()
        if height < 14 or width < 72:
            self._put(win, 0, 0, "Resize terminal to at least 72 columns x 14 rows.", max(1, width - 1), curses.A_BOLD); win.refresh(); return
        self._put(win, 0, 0, "OpenROAD Platform / L1 Agent Workbench", width - 1, curses.A_BOLD)
        self._put(win, 1, 0, f"API: {self.connection}  |  durable facts only  |  Runtime authority enabled", width - 1)
        self._put(win, 2, 0, f"Phase: {self._phase()}  |  {self.notice}", width - 1, curses.A_REVERSE)
        panel_y, panel_h, left_w = 4, height - 7, max(46, (width * 65) // 100)
        self._panel(win, "L1 AGENT HARNESS — observable execution facts", 0, panel_y, left_w, panel_h, self._harness_rows())
        self._panel(win, "USER CLIENT — input & control", left_w, panel_y, width - left_w, panel_h, self._client_rows())
        self._put(win, height - 2, 0, "Command> " + self.input_buffer, width - 1, curses.A_BOLD)
        self._put(win, height - 1, 0, "Enter submits · Backspace edits · Ctrl-C or :quit exits · Client never owns API state", width - 1)
        try: win.move(height - 2, min(width - 1, len("Command> ") + len(self.input_buffer)))
        except curses.error: pass
        win.refresh()

    def run(self, win) -> None:
        curses.curs_set(1); win.nodelay(True)
        while True:
            if self.sid and time.monotonic() - self.last_refresh >= 1.0:
                try: self.refresh()
                except Exception as exc: self.connection, self.notice = "error", f"poll error: {exc}"
            self.draw(win); key = win.getch()
            if key == -1: time.sleep(0.05); continue
            if key == 3: return
            if key in (10, 13):
                submitted, self.input_buffer = self.input_buffer.strip(), ""
                if submitted == ":quit": return
                if submitted: self.command(submitted)
            elif key in (curses.KEY_BACKSPACE, 127, 8): self.input_buffer = self.input_buffer[:-1]
            elif 32 <= key <= 126 and len(self.input_buffer) < 4096: self.input_buffer += chr(key)


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--api", default="http://127.0.0.1:8766")
    curses.wrapper(Dashboard(Client(parser.parse_args().api)).run)


if __name__ == "__main__": main()
