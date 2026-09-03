"""Read-only teaching replay stays bounded and derived from durable facts."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "apps" / "l1_workbench"))

from teaching import teaching_replay  # noqa: E402


def _events():
    return [
        {"kind": "goal_drafted",
         "facts": {"request_text": "Help improve mux setup timing with at most three runs.",
                   "clarification_questions": [{"question_id": "change_scope", "prompt": "scope?"}],
                   "clarification_answers": []},
         "planner_summary": "draft recorded"},
        {"kind": "goal_finalized",
         "facts": {"goal_ir": {"goal_id": "goal-1", "preference": "timing",
                               "hard_constraints": [{"metric": "drc_errors", "operator": "==", "threshold": 0}],
                               "allowed_tools": ["run_full_flow", "query_timing"]}},
         "planner_summary": "goal frozen"},
        {"kind": "tool_called", "tool": "run_full_flow",
         "facts": {"call_id": "call-1", "arguments": {}},
         "planner_summary": "Run one bounded full flow."},
        {"kind": "policy_decided", "tool": "run_full_flow", "policy_verdict": "allow",
         "facts": {"call_id": "call-1", "policy": {}},
         "planner_summary": "typed policy accepted call"},
        {"kind": "tool_receipt", "tool": "run_full_flow",
         "facts": {"call_id": "call-1", "status": "succeeded", "result": {"run_id": "run-1"}},
         "planner_summary": None},
        {"kind": "state_transition",
         "facts": {"run_id": "run-1", "terminal_status": "succeeded",
                   "metrics": {"setup_wns_ns": 5.9, "drc_errors": 0}},
         "planner_summary": None},
        {"kind": "reflection_recorded", "facts": {"decision": "stop", "basis_event_ids": ("e1",)},
         "planner_summary": "No measured improvement; preserve evidence and stop."},
    ]


def test_empty_trace_has_no_teaching_steps():
    assert teaching_replay([]) == []


def test_teaching_replay_explains_every_step_from_durable_facts():
    replay = teaching_replay(_events())
    assert [item["sequence"] for item in replay] == list(range(7))
    text = "\n".join(item["text"] for item in replay)
    assert "阻塞澄清问题" in replay[0]["text"]
    assert "Goal IR 已冻结" in replay[1]["text"]
    assert "工具调用已提出" in replay[2]["text"]
    assert "策略判定为 ALLOW" in replay[3]["text"]
    assert "run_id=run-1" in replay[4]["text"]
    assert "setup_wns_ns=5.9" in replay[5]["text"]
    assert "反思决策: STOP" in replay[6]["text"]


def test_teaching_lines_are_bounded_and_never_expose_hidden_markers():
    for item in teaching_replay(_events()):
        assert len(item["text"]) <= 240
        lowered = item["text"].lower()
        assert "chain of thought" not in lowered
        assert "chain-of-thought" not in lowered


def test_secrets_are_never_echoed_in_teaching_lines():
    events = [{"kind": "reflection_recorded", "facts": {"decision": "stop"},
               "planner_summary": "checked api_key=sk-abcdef secret value"}]
    line = teaching_replay(events)[0]["text"]
    assert "sk-abcdef" not in line
    # A summary that still smells like a secret is withheld entirely, which is
    # the conservative behaviour: never a partially redacted echo.
    assert line.endswith("visible teaching summary withheld")
