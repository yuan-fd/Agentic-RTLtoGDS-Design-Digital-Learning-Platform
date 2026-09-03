"""Dependency-free L1-to-L2 optimization handoff contracts.

The request describes a frozen, evidence-backed optimization campaign.  It is
not an optimizer configuration or a command envelope: the admitted external
plugin owns its algorithm and the Runtime owns execution.
"""
from __future__ import annotations

from dataclasses import dataclass

from .agent_control import AgentBudget
from .learning import EvidencePointer
from .platform import SCHEMA_VERSION, _known_payload, _primitive, _validate_identifier, _validate_version


@dataclass(frozen=True)
class OptimizationRequest:
    request_id: str
    l1_trace_id: str
    goal_id: str
    source_state_id: str
    plugin_id: str
    capability: str
    objective: str
    protocol_evidence: EvidencePointer
    search_space_evidence: EvidencePointer
    seed_policy: str
    budget: AgentBudget
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        for name, value in (("request_id", self.request_id), ("l1_trace_id", self.l1_trace_id),
                            ("goal_id", self.goal_id), ("source_state_id", self.source_state_id),
                            ("plugin_id", self.plugin_id), ("capability", self.capability)):
            _validate_identifier(name, value)
        if not isinstance(self.objective, str) or not self.objective.strip() or len(self.objective) > 256:
            raise ValueError("optimization objective must be bounded non-empty text")
        if not isinstance(self.seed_policy, str) or not self.seed_policy.strip() or len(self.seed_policy) > 128:
            raise ValueError("seed_policy must be bounded non-empty text")
        self.protocol_evidence.validate(); self.search_space_evidence.validate(); self.budget.validate()
        if self.budget.max_eda_runs < 1:
            raise ValueError("optimization request requires a positive frozen EDA budget")

    def to_dict(self) -> dict:
        self.validate(); return _primitive(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "OptimizationRequest":
        value = _known_payload(cls, payload)
        value["protocol_evidence"] = EvidencePointer.from_dict(value["protocol_evidence"])
        value["search_space_evidence"] = EvidencePointer.from_dict(value["search_space_evidence"])
        value["budget"] = AgentBudget.from_dict(value["budget"])
        result = cls(**value); result.validate(); return result


@dataclass(frozen=True)
class L2HandoffAuthorization:
    """Immutable L1 receipt that permits one external L2 submission.

    ``observed`` is intentionally not generally an L2-terminal state.  This
    receipt records the narrow exception: a frozen L1 goal has two measured
    Runtime observations and an explicit durable ``escalate`` reflection.
    It contains no optimizer parameters or command material.
    """
    authorization_id: str
    l1_trace_id: str
    goal_id: str
    source_state_id: str
    reflection_event_id: str
    baseline_run_id: str
    candidate_run_id: str
    evidence: tuple[EvidencePointer, ...]
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        for name, value in (("authorization_id", self.authorization_id),
                            ("l1_trace_id", self.l1_trace_id), ("goal_id", self.goal_id),
                            ("source_state_id", self.source_state_id),
                            ("reflection_event_id", self.reflection_event_id),
                            ("baseline_run_id", self.baseline_run_id),
                            ("candidate_run_id", self.candidate_run_id)):
            _validate_identifier(name, value)
        if self.baseline_run_id == self.candidate_run_id:
            raise ValueError("L2 handoff requires distinct measured baseline and candidate runs")
        if not isinstance(self.evidence, tuple) or not self.evidence:
            raise ValueError("L2 handoff authorization requires evidence")
        for item in self.evidence:
            if not isinstance(item, EvidencePointer):
                raise ValueError("L2 handoff authorization evidence must be typed")
            item.validate()

    def to_dict(self) -> dict:
        self.validate(); return _primitive(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "L2HandoffAuthorization":
        value = _known_payload(cls, payload)
        value["evidence"] = tuple(EvidencePointer.from_dict(item) for item in value.get("evidence", ()))
        result = cls(**value); result.validate(); return result
