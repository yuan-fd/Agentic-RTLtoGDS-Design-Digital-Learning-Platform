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
    COMMANDS = (
        ":new <goal>", ":answer <question_id> <answer>", ":baseline",
        ":m1-propose", ":candidate <proposal-id>", ":compare <baseline-run-id>",
        ":query <timing|congestion|drc|power|metrics>",
        ":artifact <report|log|run_result|config>", ":stage <allowed-stage>",
        ":cancel [reason]", ":recover   :refresh   :quit",
    )

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
                question_id, separator, value = argument.partition(" ")
                draft = next((event for event in reversed(self.events) if event.get("kind") == "goal_drafted"), None)
                questions = (draft or {}).get("facts", {}).get("clarification_questions", [])
                question = next((item for item in questions if item.get("question_id") == question_id), None)
                if not separator or not value.strip() or question is None:
                    raise ValueError("Usage: :answer <pending-question-id> <answer>")
                self.client.post(f"/api/l1/sessions/{self.sid}/answers", {"answers": [{"question_id": question_id, "field": question["field"], "value": value}]})
                self.notice = "Clarification persisted; answer remaining questions or run the frozen Goal."; self.refresh()
            elif op in {"run", "baseline"}:
                self._need_session()
                result = self.client.post(f"/api/l1/sessions/{self.sid}/execute", {
                    "decision_summary": argument or "Execute one bounded typed Runtime tool.", "wait": False})
                self.notice = f"Runtime submitted: {result['plan']['run_id']}; polling durable cursor events."; self.refresh()
            elif op == "m1-propose":
                self._need_session()
                result = self.client.post(f"/api/l1/sessions/{self.sid}/m1-proposal", {})
                self.notice = ("M1 proposal is durable, Policy-approved, and not yet executed. "
                               f"Use :candidate {result['proposal_id']}")
                self.refresh()
            elif op == "candidate":
                self._need_session()
                proposal_id = argument.strip()
                if not proposal_id: raise ValueError("Usage: :candidate <proposal-id>")
                result = self.client.post(f"/api/l1/sessions/{self.sid}/candidates", {
                    "proposal_id": proposal_id,
                    "decision_summary": "Execute the exact durable, Policy-approved M1 parameter proposal.",
                    "wait": False})
                self.notice = f"Candidate submitted: {result['plan']['run_id']}; polling durable cursor events."; self.refresh()
            elif op == "compare":
                self._need_session()
                baseline_run_id = argument.strip()
                if not baseline_run_id: raise ValueError("Usage: :compare <baseline-run-id>")
                result = self.client.post(f"/api/l1/sessions/{self.sid}/m1-compare", {
                    "baseline_run_id": baseline_run_id})
                self.notice = (f"M1 decision: {result['decision']} "
                               f"({result['decision_reason']}); area ratio={result['area_baseline_ratio']}.")
                self.refresh()
            elif op == "advance":
                self._need_session()
                result = self.client.post(f"/api/l1/sessions/{self.sid}/advance", {})
                decision = result.get("decision", {})
                self.notice = f"Teaching planner: {decision.get('action', 'recorded')} — {decision.get('summary', '')}"; self.refresh()
            elif op == "query":
                self._need_session()
                kind = argument.strip()
                if kind not in {"timing", "congestion", "drc", "power", "metrics"}:
                    raise ValueError("Usage: :query <timing|congestion|drc|power|metrics>")
                self.client.post(f"/api/l1/sessions/{self.sid}/queries", {
                    "kind": kind, "decision_summary": f"Operator requested typed {kind} evidence."})
                self.notice = f"Typed {kind} query recorded through Policy."; self.refresh()
            elif op == "artifact":
                self._need_session()
                kind = argument.strip()
                if kind not in {"report", "log", "run_result", "config"}:
                    raise ValueError("Usage: :artifact <report|log|run_result|config>")
                self.client.post(f"/api/l1/sessions/{self.sid}/artifacts", {
                    "kind": kind, "decision_summary": f"Operator requested approved {kind} excerpt."})
                self.notice = f"Approved {kind} excerpt receipt recorded."; self.refresh()
            elif op == "stage":
                self._need_session()
                stage = argument.strip()
                if not stage:
                    raise ValueError("Usage: :stage <allowed-stage>")
                result = self.client.post(f"/api/l1/sessions/{self.sid}/stages", {
                    "stage": stage, "decision_summary": f"Operator requested permitted {stage} stage.", "wait": False})
                self.notice = f"Stage submitted: {result['plan']['run_id']}; polling durable cursor events."; self.refresh()
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

    def _latest(self, kind: str):
        return next((event for event in reversed(self.events) if event.get("kind") == kind), None)

    def _goal_rows(self) -> list[str]:
        draft, final = self._latest("goal_drafted"), self._latest("goal_finalized")
        rows = ["User request / typed interpretation"]
        if draft:
            facts = draft.get("facts") or {}
            rows.append("Request: " + str(facts.get("request_text") or "recorded"))
            questions = facts.get("clarification_questions") or []
            answers = facts.get("clarification_answers") or []
            rows.append(f"Clarifications: {len(answers)}/{len(questions)} persisted")
        else:
            rows.append("No durable request yet.")
        if final:
            goal = (final.get("facts") or {}).get("goal_ir") or {}
            rows.extend(["", "Frozen Goal IR (authoritative)",
                         "goal_id: " + str(goal.get("goal_id") or final.get("goal_id") or "recorded"),
                         "objective: " + str(goal.get("preference") or "recorded"),
                         "hard constraints: " + ", ".join(
                             f"{item.get('metric')} {item.get('operator')} {item.get('threshold')}"
                             for item in goal.get("hard_constraints", [])),
                         "allowed tools: " + ", ".join(goal.get("allowed_tools") or [])])
        else:
            rows.append("Goal IR remains mutable until blocking answers are complete.")
        return rows

    def _tool_rows(self) -> list[str]:
        rows = ["Typed call → Policy → Runtime receipt"]
        selected = [e for e in self.events if e.get("kind") in {"tool_called", "policy_decided", "tool_receipt"}]
        if not selected:
            return rows + ["No admitted tool transaction yet.", "Use :advance after the Goal is frozen."]
        for event in selected[-9:]:
            facts = event.get("facts") or {}; kind = event.get("kind")
            if kind == "tool_called":
                rows.append("CALL: " + str(event.get("tool") or facts.get("tool") or "typed tool"))
                rows.append("  " + str(event.get("planner_summary") or "visible decision persisted"))
            elif kind == "policy_decided":
                rows.append("POLICY: " + str(event.get("policy_verdict") or facts.get("verdict") or "recorded").upper())
            else:
                result = facts.get("result") or {}
                rows.append("RECEIPT: " + str(facts.get("status") or "recorded") + "; run=" + str(result.get("run_id") or "n/a"))
        return rows

    def _state_rows(self) -> list[str]:
        transition = self._latest("state_transition")
        rows = ["Runtime authority / DesignState / evidence"]
        if not transition:
            return rows + ["No observed state transition yet.", "Runtime, not this client, owns terminal state."]
        facts = transition.get("facts") or {}
        state_after = facts.get("state_after") or {}
        rows.extend(["terminal: " + str(facts.get("terminal_status") or facts.get("status") or "recorded"),
                     "runtime run: " + str(facts.get("run_id") or "recorded"),
                     "state: " + str(state_after.get("state_id") or "recorded"),
                     "evidence refs: " + str(len(transition.get("evidence") or state_after.get("evidence") or []))])
        metrics = facts.get("metrics") or state_after.get("metrics") or {}
        for name in ("setup_wns_ns", "area_um2", "drc_errors"):
            rows.append(f"{name}: {metrics.get(name, 'unknown')}")
        receipt = self._latest("tool_receipt")
        if receipt:
            rows.append("last receipt sequence: " + str(receipt.get("sequence", "?")))
        return rows

    def _decision_rows(self) -> list[str]:
        reflections = [e for e in self.events if e.get("kind") == "reflection_recorded"]
        rows = ["Decision / reflection / teaching replay", "Visible summaries, never hidden chain-of-thought."]
        if not reflections:
            return rows + ["No reflection is durable yet.", "Use :advance to follow the evidence-backed tutorial policy."]
        for event in reflections[-4:]:
            facts = event.get("facts") or {}
            rows.extend([str(facts.get("decision") or "reflection").upper() + ": " + str(event.get("planner_summary") or facts.get("summary") or "recorded"),
                         "basis events: " + ", ".join(facts.get("basis_event_ids") or [])])
        return rows

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
        rows = ["You control the durable L1 Session here.", "Natural language becomes typed Goal IR; never shell text.", "", "Guided tutorial:", "  :new Improve timing; retain evidence", "  :answer objective timing", "  :answer constraints drc_zero_area_plus_3pct", "  :answer clock_sdc protect_clock_sdc", "  :answer change_scope registered_parameters_only", "  :answer budget 3", "  :advance   (repeat until STOP)", "", "Manual typed access: :query timing | :artifact report | :stage route", "", "Session", f"  id: {self.sid or 'none'}", f"  phase: {self._phase()}", f"  event cursor: {self.after}", "", "Controls"]
        rows.extend(f"  {command}" for command in self.COMMANDS)
        draft = next((e for e in reversed(self.events) if e.get("kind") == "goal_drafted"), None)
        if draft and (draft.get("facts") or {}).get("blocking_fields"):
            answered = {item.get("question_id") for item in (draft.get("facts") or {}).get("clarification_answers", [])}
            pending = [item for item in (draft.get("facts") or {}).get("clarification_questions", []) if item.get("question_id") not in answered]
            rows.extend(["", "Clarification pending"])
            for question in pending:
                rows.extend([f"  [{question.get('question_id')}] {question.get('prompt')}", f"  Reply: :answer {question.get('question_id')} <answer>"])
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
        panel_y, panel_h, left_w = 4, height - 7, max(52, (width * 68) // 100)
        half_h = max(5, panel_h // 2)
        left_half = left_w // 2
        self._panel(win, "1 GOAL / IR", 0, panel_y, left_half, half_h, self._goal_rows())
        self._panel(win, "2 TOOL / POLICY", left_half, panel_y, left_w - left_half, half_h, self._tool_rows())
        self._panel(win, "3 STATE / EVIDENCE", 0, panel_y + half_h, left_half, panel_h - half_h, self._state_rows())
        self._panel(win, "4 REFLECTION / REPLAY", left_half, panel_y + half_h, left_w - left_half, panel_h - half_h, self._decision_rows())
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
