"""Replaceable, untrusted structured-model and retrieval boundary for L1.

Providers propose typed language interpretations; policy and Runtime retain all
authority.  This module deliberately has no SDK, network client, shell, or
tool execution API.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from openroad_platform_contracts.agent_control import DesignGoal, DesignState, SemanticToolCall
from openroad_platform_contracts.l1_goal_draft import GoalDraft
from openroad_platform_contracts.l1_tool_contract import reject_forbidden_field_tree
from openroad_platform_contracts.learning import EvidencePointer

from .l1_semantic_policy import L1SemanticToolPolicy


class L1StructuredProvider(Protocol):
    """A provider may return JSON data only; it has no execution port."""
    provider_id: str

    def complete(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...


class L1KnowledgeRetriever(Protocol):
    """Read-only retrieval; returned material is never an execution capability."""
    def retrieve(self, query: str, *, limit: int) -> tuple["L1KnowledgeHit", ...]: ...


@dataclass(frozen=True)
class L1KnowledgeHit:
    excerpt: str
    evidence: EvidencePointer

    def validate(self) -> None:
        if not isinstance(self.excerpt, str) or not self.excerpt.strip() or len(self.excerpt) > 4000:
            raise ValueError("knowledge excerpt must be bounded non-empty text")
        self.evidence.validate()


@dataclass(frozen=True)
class L1ToolProposal:
    call: SemanticToolCall
    decision_summary: str
    citations: tuple[EvidencePointer, ...]

    def validate(self) -> None:
        self.call.validate()
        if not isinstance(self.decision_summary, str) or not self.decision_summary.strip() or len(self.decision_summary) > 4000:
            raise ValueError("decision summary must be bounded non-empty text")
        if not isinstance(self.citations, tuple) or not self.citations:
            raise ValueError("tool proposal requires cited retrieval evidence")
        for item in self.citations:
            item.validate()
        if not set(self.call.evidence).issubset(set(self.citations)):
            raise ValueError("tool call evidence must be supplied by retrieval")


class L1ModelBoundary:
    """Decode provider output into existing contracts, never authorize it."""
    @staticmethod
    def _output(provider: L1StructuredProvider, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(getattr(provider, "provider_id", None), str) or not provider.provider_id:
            raise ValueError("structured provider requires an identifier")
        raw = provider.complete(request)
        if not isinstance(raw, Mapping):
            raise ValueError("structured provider must return an object")
        reject_forbidden_field_tree("structured provider output", raw)
        return raw

    @classmethod
    def compile_draft(cls, provider: L1StructuredProvider, request_text: str, *, draft_id: str) -> GoalDraft:
        raw = cls._output(provider, {"kind": "goal_draft", "request_text": request_text})
        allowed = {"request_text", "intent", "questions", "answers", "interpretation", "field_sources", "schema_version"}
        if set(raw) - allowed:
            raise ValueError("goal provider returned unsupported fields")
        draft = GoalDraft.from_dict({"draft_id": draft_id, "parser_id": provider.provider_id, **raw})
        if draft.request_text != request_text:
            raise ValueError("goal provider changed the user request")
        return draft

    @staticmethod
    def retrieve(retriever: L1KnowledgeRetriever, query: str, *, limit: int = 8) -> tuple[L1KnowledgeHit, ...]:
        if not isinstance(query, str) or not query.strip() or not 1 <= limit <= 16:
            raise ValueError("retrieval query or limit is invalid")
        hits = retriever.retrieve(query, limit=limit)
        if not isinstance(hits, tuple) or len(hits) > limit:
            raise ValueError("retriever returned an invalid result set")
        for hit in hits:
            if not isinstance(hit, L1KnowledgeHit):
                raise ValueError("retriever must return typed L1KnowledgeHit values")
            hit.validate()
        return hits

    @classmethod
    def propose_tool(cls, provider: L1StructuredProvider, goal: DesignGoal, state: DesignState,
                     hits: tuple[L1KnowledgeHit, ...]) -> L1ToolProposal:
        for hit in hits:
            hit.validate()
        raw = cls._output(provider, {"kind": "tool_proposal", "goal": goal.to_dict(),
                                     "state": state.to_dict(), "knowledge": [
                                         {"excerpt": hit.excerpt, "evidence": hit.evidence.to_dict()} for hit in hits]})
        if set(raw) != {"call", "decision_summary", "citations"}:
            raise ValueError("tool provider output must contain only call, summary, and citations")
        call = SemanticToolCall.from_dict(raw["call"])
        citations = tuple(EvidencePointer.from_dict(item) for item in raw["citations"])
        proposal = L1ToolProposal(call, raw["decision_summary"], citations)
        proposal.validate()
        if set(citations) - {item.evidence for item in hits}:
            raise ValueError("tool proposal cites evidence not returned by retrieval")
        L1SemanticToolPolicy.validate(goal, state, call)
        return proposal
