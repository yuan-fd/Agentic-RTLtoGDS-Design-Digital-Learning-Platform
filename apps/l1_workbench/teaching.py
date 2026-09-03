"""Read-only teaching replay for the durable L1 event trace.

Every explanation step is derived from the stored, already-validated L1 facts
only (user request, frozen Goal IR, typed tool calls, Policy verdicts, Runtime
receipts, DesignState transitions, and visible planner reflections).  It never
renders hidden chain-of-thought, provider transcripts, commands, secrets, or
paths, and every produced line stays a single bounded sentence so it can be
shown on the dashboard without becoming an audit replacement.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

_SAFE_SUMMARY_MARKERS = (
    "chain of thought", "chain-of-thought", "hidden reasoning", "<think",
    "system prompt", "api key", "api_key", "password", "token=",
)

_GOAL_LINE_MAX = 220


def _line(value: object, maximum: int = _GOAL_LINE_MAX) -> str:
    text = " ".join(str(value or "").split())
    text = re.sub(r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*\S+", r"\1=<redacted>", text)
    text = re.sub(r"(?<!\w)/(?:[^\s'\"]+)", "<path-redacted>", text)
    if len(text) > maximum:
        text = text[: maximum - 1] + "…"
    lowered = text.lower()
    if any(marker in lowered for marker in _SAFE_SUMMARY_MARKERS):
        return "visible teaching summary withheld"
    return text


def _goal_ir(event: Mapping[str, Any]) -> Mapping[str, Any]:
    facts = event.get("facts") or {}
    value = facts.get("goal_ir")
    return value if isinstance(value, Mapping) else {}


def _metrics(facts: Mapping[str, Any]) -> str:
    metrics = facts.get("metrics")
    if not isinstance(metrics, Mapping):
        return ""
    wanted = {name: metrics[name] for name in ("setup_wns_ns", "area_um2", "drc_errors") if name in metrics}
    if not wanted:
        return ""
    return "metrics " + ", ".join(f"{name}={wanted[name]}" for name in sorted(wanted))


def _explain_one(event: Mapping[str, Any]) -> str:
    kind = event.get("kind") or "event"
    facts = event.get("facts") or {}
    summary = event.get("planner_summary")
    if kind == "goal_drafted":
        request = facts.get("request_text") or "recorded"
        questions = facts.get("clarification_questions") or ()
        answers = facts.get("clarification_answers") or ()
        if len(answers) < len(questions):
            return f"用户输入已解析为结构化草稿；还有 {len(questions) - len(answers)} 个阻塞澄清问题待回答。输入: {_line(request, 120)}"
        return f"用户输入已解析为结构化草稿（无待答阻塞问题）。输入: {_line(request, 120)}"
    if kind == "goal_finalized":
        goal = _goal_ir(event)
        constraints = ", ".join(
            f"{item.get('metric')} {item.get('operator')} {item.get('threshold')}"
            for item in goal.get("hard_constraints", ()) if isinstance(item, Mapping)
        ) or "recorded"
        tools = ", ".join(goal.get("allowed_tools") or ()) or "recorded"
        return f"Goal IR 已冻结并不可变（goal_id={goal.get('goal_id') or event.get('goal_id') or 'recorded'}）；约束: {constraints}；可用工具: {tools}"
    if kind == "tool_called":
        return f"结构化的工具调用已提出: {event.get('tool') or facts.get('tool') or 'typed tool'}。计划摘要: {_line(summary or 'recorded', 120)}"
    if kind == "policy_decided":
        verdict = event.get("policy_verdict") or facts.get("verdict") or "recorded"
        return f"策略判定为 {str(verdict).upper()}（工具与参数都必须在冻结 Goal 内）。理由: {_line(summary or 'recorded', 120)}"
    if kind == "tool_receipt":
        result = facts.get("result") or {}
        run_id = result.get("run_id") or facts.get("run_id") or "recorded"
        return f"Runtime 记录工具事实: status={facts.get('status') or 'recorded'}, run_id={run_id}"
    if kind == "state_transition":
        metric_text = _metrics(facts)
        return f"DesignState 已更新: terminal={facts.get('terminal_status') or facts.get('status') or 'recorded'}, run_id={facts.get('run_id') or 'recorded'}{('; ' + metric_text) if metric_text else ''}"
    if kind == "reflection_recorded":
        decision = facts.get("decision") or "recorded"
        return f"反思决策: {str(decision).upper()}。可见理由: {_line(summary or facts.get('summary') or 'recorded', 120)}"
    if kind == "l2_handoff_authorized":
        return f"L2 交接已授权: handoff_id={facts.get('handoff_id') or 'recorded'}"
    return f"已记录事件: {_line(summary or 'durable event recorded', 120)}"


def teaching_replay(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Map each durable event to one bounded teaching line."""
    result: list[dict[str, Any]] = []
    for sequence, event in enumerate(events):
        result.append({"sequence": int(sequence), "kind": event.get("kind") or "event",
                       "text": _explain_one(event)})
    return result
