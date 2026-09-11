"""Durable L1 language sessions, deliberately separate from the old Spec UI."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from openroad_platform_contracts.agent_control import AgentBudget, DesignGoal, GoalPreference, QoRConstraint, ToolName
from openroad_platform_contracts.l1_goal_draft import ClarificationAnswer, GoalDraft
from openroad_platform_contracts.l1_session import L1Session, L1SessionStatus
from openroad_platform_contracts.learning import EvidencePointer

from .l1_goal_finalizer import GoalFinalizer, TrustedGoalPolicy
from .l1_model_boundary import L1ModelBoundary, L1StructuredProvider
from .l1_trace_service import L1TraceService


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _policy_to_dict(value: TrustedGoalPolicy) -> dict:
    value.validate()
    return {"policy_id": value.policy_id, "policy_version": value.policy_version, "issuer": value.issuer,
            "provenance": value.provenance.to_dict(), "project_id": value.project_id,
            "design_id": value.design_id, "platform": value.platform, "pdk_id": value.pdk_id,
            "toolchain_id": value.toolchain_id, "rtl_artifact": value.rtl_artifact.to_dict(),
            "preference": value.preference.value,
            "hard_constraints": [item.to_dict() for item in value.hard_constraints],
            "allowed_stages": list(value.allowed_stages), "allowed_parameters": list(value.allowed_parameters),
            "budget": value.budget.to_dict(), "allowed_tools": [item.value for item in value.allowed_tools]}


def _policy_from_dict(value: dict) -> TrustedGoalPolicy:
    return TrustedGoalPolicy(value["policy_id"], value["policy_version"], value["issuer"],
        EvidencePointer.from_dict(value["provenance"]), value["project_id"], value["design_id"],
        value["platform"], value["pdk_id"], value["toolchain_id"],
        EvidencePointer.from_dict(value["rtl_artifact"]), GoalPreference(value["preference"]),
        tuple(QoRConstraint.from_dict(item) for item in value["hard_constraints"]),
        tuple(value["allowed_stages"]), tuple(value["allowed_parameters"]),
        AgentBudget.from_dict(value["budget"]), tuple(ToolName(item) for item in value["allowed_tools"]))


class L1SessionStore:
    """Stores only session heads and trusted policy; trace remains event authority."""
    def __init__(self, database: str | Path) -> None:
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS l1_session (
                session_id TEXT PRIMARY KEY, trace_id TEXT NOT NULL UNIQUE, project_id TEXT NOT NULL,
                status TEXT NOT NULL, draft_json TEXT NOT NULL, policy_json TEXT NOT NULL,
                goal_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")

    def _connect(self):
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        return connection

    def create(self, session_id: str, trace_id: str, draft: GoalDraft, policy: TrustedGoalPolicy) -> L1Session:
        draft.validate(); policy.validate(); now = _now()
        with self._connect() as connection:
            connection.execute("INSERT INTO l1_session VALUES(?,?,?,?,?,?,?,?,?)", (
                session_id, trace_id, policy.project_id, L1SessionStatus.CREATING.value,
                json.dumps(draft.to_dict(), sort_keys=True), json.dumps(_policy_to_dict(policy), sort_keys=True),
                None, now, now))
        return self.get(session_id)

    def get(self, session_id: str) -> L1Session:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM l1_session WHERE session_id=?", (session_id,)).fetchone()
        if row is None: raise KeyError("unknown L1 session")
        return L1Session(row["session_id"], row["trace_id"], row["project_id"], L1SessionStatus(row["status"]),
                         GoalDraft.from_dict(json.loads(row["draft_json"])).draft_id,
                         json.loads(row["goal_json"])["goal_id"] if row["goal_json"] else None,
                         row["created_at"], row["updated_at"])

    def draft_and_policy(self, session_id: str) -> tuple[GoalDraft, TrustedGoalPolicy]:
        with self._connect() as connection:
            row = connection.execute("SELECT draft_json,policy_json FROM l1_session WHERE session_id=?", (session_id,)).fetchone()
        if row is None: raise KeyError("unknown L1 session")
        return GoalDraft.from_dict(json.loads(row["draft_json"])), _policy_from_dict(json.loads(row["policy_json"]))

    def update(self, session_id: str, draft: GoalDraft, status: L1SessionStatus, goal=None) -> L1Session:
        draft.validate(); now = _now(); goal_json = json.dumps(goal.to_dict(), sort_keys=True) if goal else None
        with self._connect() as connection:
            if connection.execute("UPDATE l1_session SET draft_json=?, status=?, goal_json=?, updated_at=? WHERE session_id=?", (
                    json.dumps(draft.to_dict(), sort_keys=True), status.value, goal_json, now, session_id)).rowcount != 1:
                raise KeyError("unknown L1 session")
        return self.get(session_id)

    def prepare(self, session_id: str, draft: GoalDraft) -> L1Session:
        """Durably stage a draft before its trace append; recovery can resume it."""
        return self.update(session_id, draft, L1SessionStatus.CREATING)


class L1SessionService:
    """Owns durable language-session heads, never a tool or Runtime operation."""
    def __init__(self, store: L1SessionStore, trace: L1TraceService, *, goal_finalizer=None) -> None:
        self.store, self.trace = store, trace
        # Composition may select a stricter profile compiler.  It receives only
        # a typed draft and trusted policy and must return DesignGoal; it never
        # receives Runtime, tools, shell text, or mutable workspace access.
        self.goal_finalizer = goal_finalizer or GoalFinalizer.finalize

    def start(
        self, request_text: str, provider: L1StructuredProvider,
        policy: TrustedGoalPolicy, *, required_questions=(),
    ) -> L1Session:
        draft = L1ModelBoundary.compile_draft(
            provider, request_text, draft_id=f"draft-{uuid4().hex}",
            required_questions=tuple(required_questions),
        )
        session_id, trace_id = f"l1-session-{uuid4().hex}", f"l1-trace-{uuid4().hex}"
        self.store.create(session_id, trace_id, draft, policy)
        return self._record_and_finalize(session_id, draft, policy)

    def answer(self, session_id: str, provider: L1StructuredProvider,
               answers: tuple[ClarificationAnswer, ...]) -> L1Session:
        prior, policy = self.store.draft_and_policy(session_id)
        if self.store.get(session_id).status is not L1SessionStatus.CLARIFICATION_REQUIRED:
            raise ValueError("L1 session is not awaiting clarification")
        if not isinstance(answers, tuple) or len({item.question_id for item in answers}) != len(answers):
            raise ValueError("clarification answers must have unique question ids")
        prior_questions = {item.question_id: item for item in prior.questions}
        prior_answers = {item.question_id: item for item in prior.answers}
        for answer in answers:
            answer.validate()
            if prior_questions.get(answer.question_id) is None or prior_questions[answer.question_id].field is not answer.field:
                raise ValueError("clarification answer is not for a pending question")
            if answer.question_id in prior_answers:
                raise ValueError("clarification answer was already recorded")
        merged_answers = tuple((*prior.answers, *answers))
        raw = L1ModelBoundary._output(provider, {"kind": "goal_draft_revision", "request_text": prior.request_text,
                                                 "prior_draft": prior.to_dict(), "answers": [item.to_dict() for item in merged_answers]})
        allowed = {"request_text", "intent", "questions", "answers", "interpretation", "field_sources", "schema_version"}
        if set(raw) - allowed: raise ValueError("goal provider returned unsupported fields")
        draft = GoalDraft.from_dict({"draft_id": f"draft-{uuid4().hex}", "parser_id": provider.provider_id, **raw})
        if (draft.request_text != prior.request_text or tuple(draft.answers) != merged_answers
                or draft.interpretation != prior.interpretation or draft.field_sources != prior.field_sources):
            raise ValueError("goal revision must preserve request and all typed answers")
        if draft.questions != prior.questions:
            raise ValueError("goal revision changed the operator-owned question schema")
        self.store.prepare(session_id, draft)
        return self._record_and_finalize(session_id, draft, policy)

    def events(self, session_id: str, *, after_sequence: int = -1):
        if not isinstance(after_sequence, int) or after_sequence < -1: raise ValueError("event cursor is invalid")
        return tuple(event for event in self.trace.store.read(self.store.get(session_id).trace_id)
                     if event.sequence > after_sequence)

    def recover(self, session_id: str) -> L1Session:
        """Resume only a staged language/goal transition; never execute a tool."""
        session = self.store.get(session_id)
        if session.status is not L1SessionStatus.CREATING:
            return session
        draft, policy = self.store.draft_and_policy(session_id)
        return self._record_and_finalize(session_id, draft, policy)

    def _record_and_finalize(self, session_id: str, draft: GoalDraft, policy: TrustedGoalPolicy) -> L1Session:
        session = self.store.get(session_id)
        events = self.trace.store.read(session.trace_id)
        if not any(event.kind.value == "goal_drafted" and event.goal_id == draft.draft_id for event in events):
            self.trace.record_draft(session.trace_id, draft)
        if draft.unresolved_blocking_fields():
            return self.store.update(session_id, draft, L1SessionStatus.CLARIFICATION_REQUIRED)
        goal_id = f"goal-{session.session_id.removeprefix('l1-session-')}"
        finalized = next((event for event in self.trace.store.read(session.trace_id)
                          if event.kind.value == "goal_finalized" and event.goal_id == goal_id), None)
        goal = (DesignGoal.from_dict(finalized.facts["goal_ir"]) if finalized
                else self.goal_finalizer(draft, policy, goal_id=goal_id))
        if finalized is None:
            self.trace.record_goal(session.trace_id, goal)
        return self.store.update(session_id, draft, L1SessionStatus.GOAL_FINALIZED, goal)
