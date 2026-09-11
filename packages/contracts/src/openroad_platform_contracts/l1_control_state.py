"""Typed Planner/Analyzer/Debugger control-state contracts for L1."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from .learning import EvidencePointer
from .platform import (
    SCHEMA_VERSION, _known_payload, _primitive, _validate_identifier,
    _validate_version,
)


class PlannerPhase(str, Enum):
    PLANNING = "planning"
    AWAITING_RUNTIME = "awaiting_runtime"
    ANALYZING = "analyzing"
    DEBUGGING = "debugging"
    REVIEWING = "reviewing"
    ROLLBACK_PENDING = "rollback_pending"
    COMPLETED = "completed"
    ESCALATED = "escalated"
    FAILED = "failed"


class ConvergenceState(str, Enum):
    UNKNOWN = "unknown"
    IMPROVING = "improving"
    STALLED = "stalled"
    DIVERGING = "diverging"


class RecoveryClass(str, Enum):
    MICRO = "micro"
    MESO = "meso"
    MACRO = "macro"


class RecoveryAction(str, Enum):
    CONTINUE = "continue"
    RETRY = "retry"
    REQUEST_TYPED_FIX = "request_typed_fix"
    ROLLBACK = "rollback"
    SKIP = "skip"
    ESCALATE_L2 = "escalate_l2"
    STOP = "stop"


_STAGES = frozenset({"synth", "floorplan", "place", "cts", "route", "finish"})


def _evidence(values: tuple[EvidencePointer, ...]) -> None:
    if not isinstance(values, tuple) or not values or len(set(values)) != len(values):
        raise ValueError("control state requires unique evidence")
    for item in values:
        if not isinstance(item, EvidencePointer):
            raise ValueError("control evidence must be typed")
        item.validate()


def _ids(name: str, values: tuple[str, ...], *, required: bool = False) -> None:
    if not isinstance(values, tuple) or (required and not values):
        raise ValueError(f"{name} must be a tuple")
    if len(set(values)) != len(values):
        raise ValueError(f"{name} must be unique")
    for item in values:
        _validate_identifier(name, item)


@dataclass(frozen=True)
class RecoveryBudget:
    micro_remaining: int = 2
    meso_remaining: int = 4
    macro_remaining: int = 2
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        for name, value in (("micro_remaining", self.micro_remaining),
                            ("meso_remaining", self.meso_remaining),
                            ("macro_remaining", self.macro_remaining)):
            if (not isinstance(value, int) or isinstance(value, bool)
                    or not 0 <= value <= 100):
                raise ValueError(f"{name} is outside recovery policy")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RecoveryBudget":
        result = cls(**_known_payload(cls, payload))
        result.validate()
        return result

    def consume(self, recovery_class: RecoveryClass) -> "RecoveryBudget":
        if not isinstance(recovery_class, RecoveryClass):
            raise ValueError("recovery class must be typed")
        values = {
            "micro_remaining": self.micro_remaining,
            "meso_remaining": self.meso_remaining,
            "macro_remaining": self.macro_remaining,
        }
        field = f"{recovery_class.value}_remaining"
        if values[field] < 1:
            raise ValueError(f"{recovery_class.value} recovery budget is exhausted")
        values[field] -= 1
        return RecoveryBudget(**values)


@dataclass(frozen=True)
class PlannerState:
    planner_state_id: str
    goal_id: str
    revision: int
    phase: PlannerPhase
    stage_plan: tuple[str, ...]
    stage_index: int
    convergence: ConvergenceState
    recovery_budget: RecoveryBudget
    evidence: tuple[EvidencePointer, ...]
    convergence_assessment_id: str | None = None
    last_run_id: str | None = None
    diagnosis_report_id: str | None = None
    parent_state_id: str | None = None
    schema_version: int = SCHEMA_VERSION

    @property
    def current_stage(self) -> str | None:
        return (self.stage_plan[self.stage_index]
                if self.stage_index < len(self.stage_plan) else None)

    def validate(self) -> None:
        _validate_version(self.schema_version)
        for name, value, required in (
            ("planner_state_id", self.planner_state_id, True),
            ("goal_id", self.goal_id, True),
            ("last_run_id", self.last_run_id, False),
            ("diagnosis_report_id", self.diagnosis_report_id, False),
            ("convergence_assessment_id", self.convergence_assessment_id, False),
            ("parent_state_id", self.parent_state_id, False),
        ):
            _validate_identifier(name, value, required=required)
        if not isinstance(self.revision, int) or isinstance(self.revision, bool) or self.revision < 0:
            raise ValueError("planner revision must be non-negative")
        if not isinstance(self.phase, PlannerPhase):
            raise ValueError("planner phase must be typed")
        if (not isinstance(self.stage_plan, tuple) or not self.stage_plan
                or any(item not in _STAGES for item in self.stage_plan)
                or len(set(self.stage_plan)) != len(self.stage_plan)):
            raise ValueError("planner stage plan is invalid")
        if (not isinstance(self.stage_index, int) or isinstance(self.stage_index, bool)
                or not 0 <= self.stage_index <= len(self.stage_plan)):
            raise ValueError("planner stage index is invalid")
        if not isinstance(self.convergence, ConvergenceState):
            raise ValueError("planner convergence must be typed")
        self.recovery_budget.validate()
        _evidence(self.evidence)
        if self.phase in {PlannerPhase.AWAITING_RUNTIME, PlannerPhase.ANALYZING,
                          PlannerPhase.DEBUGGING, PlannerPhase.REVIEWING,
                          PlannerPhase.ROLLBACK_PENDING} and not self.last_run_id:
            raise ValueError("active post-submission phase requires a Runtime run")
        if self.phase in {PlannerPhase.DEBUGGING, PlannerPhase.REVIEWING,
                          PlannerPhase.ROLLBACK_PENDING} and not self.diagnosis_report_id:
            raise ValueError("diagnostic phase requires a DiagnosisReport")
        if self.phase is PlannerPhase.COMPLETED and self.stage_index != len(self.stage_plan):
            raise ValueError("completed planner must finish its stage plan")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PlannerState":
        value = _known_payload(cls, payload)
        value["phase"] = PlannerPhase(value["phase"])
        value["convergence"] = ConvergenceState(value["convergence"])
        value["recovery_budget"] = RecoveryBudget.from_dict(value["recovery_budget"])
        value["stage_plan"] = tuple(value.get("stage_plan", ()))
        value["evidence"] = tuple(EvidencePointer.from_dict(item)
                                  for item in value.get("evidence", ()))
        result = cls(**value)
        result.validate()
        return result


@dataclass(frozen=True)
class AnalyzerState:
    analyzer_state_id: str
    planner_state_id: str
    run_id: str
    status: str
    analysis_ids: tuple[str, ...]
    evidence: tuple[EvidencePointer, ...]
    diagnosis_report_id: str | None = None
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        for name, value, required in (
            ("analyzer_state_id", self.analyzer_state_id, True),
            ("planner_state_id", self.planner_state_id, True),
            ("run_id", self.run_id, True),
            ("diagnosis_report_id", self.diagnosis_report_id, False),
        ):
            _validate_identifier(name, value, required=required)
        if self.status not in {"requested", "completed", "failed"}:
            raise ValueError("analyzer status is unsupported")
        _ids("analysis_ids", self.analysis_ids,
             required=self.status == "completed")
        if self.status == "completed" and not self.diagnosis_report_id:
            raise ValueError("completed analyzer state requires DiagnosisReport")
        _evidence(self.evidence)

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AnalyzerState":
        value = _known_payload(cls, payload)
        value["analysis_ids"] = tuple(value.get("analysis_ids", ()))
        value["evidence"] = tuple(EvidencePointer.from_dict(item)
                                  for item in value.get("evidence", ()))
        result = cls(**value)
        result.validate()
        return result


@dataclass(frozen=True)
class DebuggerState:
    debugger_state_id: str
    planner_state_id: str
    diagnosis_report_id: str
    status: str
    blockers: tuple[str, ...]
    basis_fact_ids: tuple[str, ...]
    evidence: tuple[EvidencePointer, ...]
    proposed_action: RecoveryAction | None = None
    recovery_class: RecoveryClass | None = None
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        for name, value in (("debugger_state_id", self.debugger_state_id),
                            ("planner_state_id", self.planner_state_id),
                            ("diagnosis_report_id", self.diagnosis_report_id)):
            _validate_identifier(name, value)
        if self.status not in {"investigating", "action_proposed", "resolved", "escalated"}:
            raise ValueError("debugger status is unsupported")
        _ids("blockers", self.blockers, required=True)
        # A terminal Runtime failure can precede every QoR parser. In that
        # case the debugger is grounded by the required run/artifact evidence
        # below, while an empty numeric-fact basis honestly remains empty.
        _ids("basis_fact_ids", self.basis_fact_ids)
        _evidence(self.evidence)
        if self.status == "action_proposed":
            if not isinstance(self.proposed_action, RecoveryAction):
                raise ValueError("debugger action must be typed")
            if (self.proposed_action in {RecoveryAction.RETRY,
                                         RecoveryAction.REQUEST_TYPED_FIX,
                                         RecoveryAction.ROLLBACK}
                    and not isinstance(self.recovery_class, RecoveryClass)):
                raise ValueError("retry/fix/rollback requires a recovery class")
        elif self.proposed_action is not None or self.recovery_class is not None:
            raise ValueError("only action_proposed may carry a recovery action")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "DebuggerState":
        value = _known_payload(cls, payload)
        for name in ("blockers", "basis_fact_ids"):
            value[name] = tuple(value.get(name, ()))
        value["evidence"] = tuple(EvidencePointer.from_dict(item)
                                  for item in value.get("evidence", ()))
        if value.get("proposed_action") is not None:
            value["proposed_action"] = RecoveryAction(value["proposed_action"])
        if value.get("recovery_class") is not None:
            value["recovery_class"] = RecoveryClass(value["recovery_class"])
        result = cls(**value)
        result.validate()
        return result
