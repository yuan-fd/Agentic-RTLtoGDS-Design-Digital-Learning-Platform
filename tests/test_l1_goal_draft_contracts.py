from __future__ import annotations

import pytest

from openroad_platform_contracts.l1_goal_draft import (
    ClarificationAnswer,
    ClarificationField,
    ClarificationQuestion,
    GoalDraft,
    GoalIntent,
)


def _draft() -> GoalDraft:
    return GoalDraft(
        draft_id="draft-1", request_text="Improve setup timing without changing clock.",
        intent=GoalIntent.OPTIMIZE,
        questions=(ClarificationQuestion("question-1", ClarificationField.DESIGN_CONTEXT,
                                         "Which verified design should be used?"),),
        parser_id="llm-provider-v1",
    )


def test_goal_draft_preserves_request_digest_and_requires_blocking_answer() -> None:
    draft = _draft()
    assert len(draft.request_sha256) == 64
    assert draft.unresolved_blocking_fields() == (ClarificationField.DESIGN_CONTEXT,)
    completed = GoalDraft(
        **{**draft.__dict__, "answers": (ClarificationAnswer(
            "question-1", ClarificationField.DESIGN_CONTEXT, "verified-aes-sky130"),)}
    )
    assert completed.unresolved_blocking_fields() == ()
    assert GoalDraft.from_dict(completed.to_dict()) == completed


def test_goal_draft_rejects_unmatched_or_duplicate_answers() -> None:
    draft = _draft()
    with pytest.raises(ValueError, match="does not match"):
        GoalDraft(**{**draft.__dict__, "answers": (
            ClarificationAnswer("missing", ClarificationField.DESIGN_CONTEXT, "aes"),
        )}).validate()
    answer = ClarificationAnswer("question-1", ClarificationField.DESIGN_CONTEXT, "aes")
    with pytest.raises(ValueError, match="answers must be unique"):
        GoalDraft(**{**draft.__dict__, "answers": (answer, answer)}).validate()
