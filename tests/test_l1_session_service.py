from pathlib import Path
import hashlib
import pytest
from openroad_platform_contracts.agent_control import AgentBudget, GoalPreference, QoRConstraint, ToolName
from openroad_platform_contracts.l1_goal_draft import (
    ClarificationAnswer, ClarificationField, ClarificationQuestion,
)
from openroad_platform_contracts.learning import EvidencePointer
from openroad_platform_contracts.l1_session import L1SessionStatus
from openroad_platform_scheduler.l1_goal_finalizer import TrustedGoalPolicy
from openroad_platform_scheduler.l1_session_service import L1SessionService, L1SessionStore
from openroad_platform_scheduler.l1_trace_service import L1TraceService
from openroad_platform_scheduler.l1_trace_store import L1TraceStore

class _Provider:
    provider_id = "session-fixture"
    def __init__(self, values): self.values = iter(values)
    def complete(self, request): return next(self.values)

def _pointer(ref): return EvidencePointer(ref, hashlib.sha256(ref.encode()).hexdigest())
def _policy():
    return TrustedGoalPolicy("policy-1", "v1", "platform", _pointer("artifact:policy"), "p1", "top", "platform-1", "pdk-1", "toolchain-1", _pointer("artifact:rtl"), GoalPreference.BALANCED, (QoRConstraint("setup_wns_ns", ">=", 0),), ("route",), ("density",), AgentBudget(1, 2, 60), (ToolName.QUERY_TIMING,))

def test_l1_session_persists_clarification_goal_and_cursor_events(tmp_path: Path):
    request = "Inspect timing for top."
    question = {"question_id": "q-1", "field": "constraints", "prompt": "What timing target?", "blocking": True, "schema_version": 1}
    provider = _Provider([
        {"request_text": request, "intent": "diagnose", "questions": [question], "answers": [], "schema_version": 1},
        {"request_text": request, "intent": "diagnose", "questions": [question], "answers": [{"question_id": "q-1", "field": "constraints", "value": "WNS at least zero", "schema_version": 1}], "schema_version": 1},
    ])
    trace = L1TraceService(L1TraceStore(tmp_path / "trace.sqlite"))
    service = L1SessionService(L1SessionStore(tmp_path / "sessions.sqlite"), trace)
    created = service.start(
        request, provider, _policy(),
        required_questions=(ClarificationQuestion.from_dict(question),),
    )
    assert created.status is L1SessionStatus.CLARIFICATION_REQUIRED
    finalized = service.answer(created.session_id, provider, (ClarificationAnswer("q-1", ClarificationField.CONSTRAINTS, "WNS at least zero"),))
    assert finalized.status is L1SessionStatus.GOAL_FINALIZED and finalized.goal_id
    events = service.events(finalized.session_id)
    assert [event.kind.value for event in events] == ["goal_drafted", "goal_drafted", "goal_finalized"]
    assert service.events(finalized.session_id, after_sequence=1)[0].kind.value == "goal_finalized"
    assert L1SessionStore(tmp_path / "sessions.sqlite").get(finalized.session_id) == finalized

def test_l1_session_rejects_answer_when_not_pending(tmp_path: Path):
    provider = _Provider([{"request_text": "Inspect timing.", "intent": "diagnose", "questions": [], "answers": [], "schema_version": 1}])
    service = L1SessionService(L1SessionStore(tmp_path / "sessions.sqlite"), L1TraceService(L1TraceStore(tmp_path / "trace.sqlite")))
    session = service.start("Inspect timing.", provider, _policy())
    with pytest.raises(ValueError, match="not awaiting"):
        service.answer(session.session_id, provider, ())

def test_l1_session_recovers_a_staged_draft_without_tool_execution(tmp_path: Path):
    request = "Inspect timing."
    provider = _Provider([{"request_text": request, "intent": "diagnose", "questions": [], "answers": [], "schema_version": 1}])
    trace = L1TraceService(L1TraceStore(tmp_path / "trace.sqlite"))
    store = L1SessionStore(tmp_path / "sessions.sqlite")
    service = L1SessionService(store, trace)
    from openroad_platform_scheduler.l1_model_boundary import L1ModelBoundary
    draft = L1ModelBoundary.compile_draft(provider, request, draft_id="draft-recovery")
    staged = store.create("l1-session-recovery", "l1-trace-recovery", draft, _policy())
    assert staged.status is L1SessionStatus.CREATING
    recovered = service.recover(staged.session_id)
    assert recovered.status is L1SessionStatus.GOAL_FINALIZED
    assert [event.kind.value for event in service.events(recovered.session_id)] == ["goal_drafted", "goal_finalized"]

def test_l1_session_recovery_is_idempotent_after_goal_trace_append(tmp_path: Path):
    request = "Inspect timing."
    provider = _Provider([{"request_text": request, "intent": "diagnose", "questions": [], "answers": [], "schema_version": 1}])
    trace = L1TraceService(L1TraceStore(tmp_path / "trace.sqlite")); store = L1SessionStore(tmp_path / "sessions.sqlite")
    from openroad_platform_scheduler.l1_model_boundary import L1ModelBoundary
    from openroad_platform_scheduler.l1_goal_finalizer import GoalFinalizer
    draft = L1ModelBoundary.compile_draft(provider, request, draft_id="draft-goal-recovery")
    session = store.create("l1-session-goal-recovery", "l1-trace-goal-recovery", draft, _policy())
    trace.record_draft(session.trace_id, draft)
    goal = GoalFinalizer.finalize(draft, _policy(), goal_id="goal-goal-recovery")
    trace.record_goal(session.trace_id, goal)  # Simulates crash before session-head update.
    service = L1SessionService(store, trace)
    assert service.recover(session.session_id).status is L1SessionStatus.GOAL_FINALIZED
    assert len(service.events(session.session_id)) == 2

def test_l1_session_requires_all_prior_blocking_questions_across_turns(tmp_path: Path):
    request = "Inspect timing for top."
    q1 = {"question_id": "q-1", "field": "constraints", "prompt": "Target?", "blocking": True, "schema_version": 1}
    q2 = {"question_id": "q-2", "field": "budget", "prompt": "Budget?", "blocking": True, "schema_version": 1}
    answer1 = {"question_id": "q-1", "field": "constraints", "value": "WNS >= 0", "schema_version": 1}
    answer2 = {"question_id": "q-2", "field": "budget", "value": "one run", "schema_version": 1}
    provider = _Provider([
        {"request_text": request, "intent": "diagnose", "questions": [q1, q2], "answers": [], "schema_version": 1},
        {"request_text": request, "intent": "diagnose", "questions": [q1, q2], "answers": [answer1], "schema_version": 1},
        {"request_text": request, "intent": "diagnose", "questions": [q1, q2], "answers": [answer1, answer2], "schema_version": 1},
    ])
    service = L1SessionService(L1SessionStore(tmp_path / "sessions.sqlite"), L1TraceService(L1TraceStore(tmp_path / "trace.sqlite")))
    session = service.start(
        request, provider, _policy(), required_questions=tuple(
            ClarificationQuestion.from_dict(item) for item in (q1, q2)
        ),
    )
    session = service.answer(session.session_id, provider, (ClarificationAnswer("q-1", ClarificationField.CONSTRAINTS, "WNS >= 0"),))
    assert session.status is L1SessionStatus.CLARIFICATION_REQUIRED
    session = service.answer(session.session_id, provider, (ClarificationAnswer("q-2", ClarificationField.BUDGET, "one run"),))
    assert session.status is L1SessionStatus.GOAL_FINALIZED

@pytest.mark.parametrize("revision", [
    {"questions": [{"question_id": "q-1", "field": "constraints", "prompt": "Target?", "blocking": True, "schema_version": 1}]},
    {"questions": [{"question_id": "q-1", "field": "constraints", "prompt": "Target?", "blocking": True, "schema_version": 1}, {"question_id": "q-2", "field": "budget", "prompt": "Budget?", "blocking": False, "schema_version": 1}]},
])
def test_l1_session_rejects_provider_removing_or_weakening_prior_question(tmp_path: Path, revision):
    request = "Inspect timing for top."
    q1 = {"question_id": "q-1", "field": "constraints", "prompt": "Target?", "blocking": True, "schema_version": 1}
    q2 = {"question_id": "q-2", "field": "budget", "prompt": "Budget?", "blocking": True, "schema_version": 1}
    a1 = {"question_id": "q-1", "field": "constraints", "value": "WNS >= 0", "schema_version": 1}
    provider = _Provider([
        {"request_text": request, "intent": "diagnose", "questions": [q1, q2], "answers": [], "schema_version": 1},
        {"request_text": request, "intent": "diagnose", "questions": revision["questions"], "answers": [a1], "schema_version": 1},
    ])
    service = L1SessionService(L1SessionStore(tmp_path / "sessions.sqlite"), L1TraceService(L1TraceStore(tmp_path / "trace.sqlite")))
    session = service.start(
        request, provider, _policy(), required_questions=tuple(
            ClarificationQuestion.from_dict(item) for item in (q1, q2)
        ),
    )
    with pytest.raises(ValueError, match="operator-owned question schema"):
        service.answer(session.session_id, provider, (ClarificationAnswer("q-1", ClarificationField.CONSTRAINTS, "WNS >= 0"),))
