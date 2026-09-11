"""Typed L1 recovery and external-L2 escalation decisions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from .l1_control_state import RecoveryAction, RecoveryClass
from .learning import EvidencePointer, SHA256
from .platform import (
    SCHEMA_VERSION, _known_payload, _primitive, _validate_identifier,
    _validate_version,
)


class RuntimeFailureClass(str, Enum):
    NONE = "none"
    TRANSIENT_INFRASTRUCTURE = "transient_infrastructure"
    RESOURCE_LIMIT = "resource_limit"
    EDA_CONFIGURATION = "eda_configuration"
    DESIGN = "design"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RTLCheckpointRestorePlan:
    """Bounded RTL selection after a typed recovery decision.

    The plan identifies an already registered, content-addressed candidate. It
    intentionally carries neither source text, a patch, parameters, nor a
    shell command. Verification and implementation remain separate Runtime
    submissions after the selection is admitted.
    """

    plan_id: str
    recovery_decision_id: str
    checkpoint_id: str
    failed_candidate_id: str
    target_candidate_id: str
    target_rtl_sha256: str
    evidence: tuple[EvidencePointer, ...]
    policy_id: str = "rtl-checkpoint-restore-v1"
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        for name, value in (
            ("plan_id", self.plan_id),
            ("recovery_decision_id", self.recovery_decision_id),
            ("checkpoint_id", self.checkpoint_id),
            ("failed_candidate_id", self.failed_candidate_id),
            ("target_candidate_id", self.target_candidate_id),
            ("policy_id", self.policy_id),
        ):
            _validate_identifier(name, value)
        if self.failed_candidate_id == self.target_candidate_id:
            raise ValueError("RTL restore target must differ from failed candidate")
        if not isinstance(self.target_rtl_sha256, str) or not SHA256.fullmatch(
                self.target_rtl_sha256):
            raise ValueError("RTL restore target requires SHA-256")
        _evidence(self.evidence)
        expected_ref = f"artifact:rtl-candidate:{self.target_rtl_sha256}"
        if not any(item.ref == expected_ref and item.sha256 == self.target_rtl_sha256
                   for item in self.evidence):
            raise ValueError("RTL restore evidence does not bind target content")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RTLCheckpointRestorePlan":
        value = _known_payload(cls, payload)
        value["evidence"] = tuple(EvidencePointer.from_dict(item)
                                  for item in value.get("evidence", ()))
        result = cls(**value)
        result.validate()
        return result


def _evidence(values: tuple[EvidencePointer, ...]) -> None:
    if not isinstance(values, tuple) or not values or len(set(values)) != len(values):
        raise ValueError("recovery record requires unique evidence")
    for item in values:
        if not isinstance(item, EvidencePointer):
            raise ValueError("recovery evidence must be typed")
        item.validate()


@dataclass(frozen=True)
class RollbackCheckpoint:
    checkpoint_id: str
    goal_id: str
    planner_state_id: str
    revision: int
    stage: str
    stage_index: int
    run_id: str
    protocol_sha256: str
    evidence: tuple[EvidencePointer, ...]
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        for name, value in (("checkpoint_id", self.checkpoint_id),
                            ("goal_id", self.goal_id),
                            ("planner_state_id", self.planner_state_id),
                            ("stage", self.stage), ("run_id", self.run_id)):
            _validate_identifier(name, value)
        for name, value in (("revision", self.revision),
                            ("stage_index", self.stage_index)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"rollback {name} must be non-negative")
        if not isinstance(self.protocol_sha256, str) or not SHA256.fullmatch(
                self.protocol_sha256):
            raise ValueError("rollback checkpoint requires protocol SHA-256")
        _evidence(self.evidence)

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RollbackCheckpoint":
        value = _known_payload(cls, payload)
        value["evidence"] = tuple(EvidencePointer.from_dict(item)
                                  for item in value.get("evidence", ()))
        result = cls(**value)
        result.validate()
        return result


@dataclass(frozen=True)
class RecoveryDecision:
    decision_id: str
    planner_state_id: str
    diagnosis_report_id: str
    convergence_assessment_id: str
    action: RecoveryAction
    reason_code: str
    evidence: tuple[EvidencePointer, ...]
    recovery_class: RecoveryClass | None = None
    rollback_checkpoint_id: str | None = None
    l2_authorization_id: str | None = None
    l2_plugin_id: str | None = None
    l2_capability: str | None = None
    policy_id: str = "l1-recovery-policy-v1"
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        for name, value, required in (
            ("decision_id", self.decision_id, True),
            ("planner_state_id", self.planner_state_id, True),
            ("diagnosis_report_id", self.diagnosis_report_id, True),
            ("convergence_assessment_id", self.convergence_assessment_id, True),
            ("reason_code", self.reason_code, True),
            ("rollback_checkpoint_id", self.rollback_checkpoint_id, False),
            ("l2_authorization_id", self.l2_authorization_id, False),
            ("l2_plugin_id", self.l2_plugin_id, False),
            ("l2_capability", self.l2_capability, False),
            ("policy_id", self.policy_id, True),
        ):
            _validate_identifier(name, value, required=required)
        if not isinstance(self.action, RecoveryAction):
            raise ValueError("recovery decision action must be typed")
        expected_class = {
            RecoveryAction.RETRY: RecoveryClass.MICRO,
            RecoveryAction.REQUEST_TYPED_FIX: RecoveryClass.MESO,
            RecoveryAction.ROLLBACK: RecoveryClass.MACRO,
        }.get(self.action)
        if self.recovery_class is not expected_class:
            raise ValueError("recovery decision class does not match action")
        if (self.action is RecoveryAction.ROLLBACK) != bool(self.rollback_checkpoint_id):
            raise ValueError("rollback decision requires exactly one checkpoint")
        escalation = self.action is RecoveryAction.ESCALATE_L2
        if escalation != all((self.l2_authorization_id, self.l2_plugin_id,
                              self.l2_capability)):
            raise ValueError("L2 escalation requires authorization and target capability")
        if not escalation and any((self.l2_authorization_id, self.l2_plugin_id,
                                   self.l2_capability)):
            raise ValueError("non-escalation decision cannot carry an L2 target")
        _evidence(self.evidence)

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RecoveryDecision":
        value = _known_payload(cls, payload)
        value["action"] = RecoveryAction(value["action"])
        if value.get("recovery_class") is not None:
            value["recovery_class"] = RecoveryClass(value["recovery_class"])
        value["evidence"] = tuple(EvidencePointer.from_dict(item)
                                  for item in value.get("evidence", ()))
        result = cls(**value)
        result.validate()
        return result
