"""M1-owned records. Raw RTL and EDA outputs remain in v2."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from openroad_platform_contracts.rtl_frontend import SpecIR


class M1State(str, Enum):
    NEEDS_CLARIFICATION = "needs_clarification"
    UNSUPPORTED_SCOPE = "unsupported_scope"
    SPECIFIED = "specified"
    FROZEN = "frozen"
    RTL_VERSIONED = "rtl_versioned"
    VERIFIED = "verified"
    SUBMITTED = "submitted"
    MEASURED = "measured"
    FAILED = "failed"
    INCOMPLETE = "incomplete"


class VerificationStatus(str, Enum):
    NOT_RUN = "not_run"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    INVALIDATED = "invalidated"


class SimulationStatus(str, Enum):
    NOT_RUN = "not_run"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    INVALIDATED = "invalidated"


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _id(name: str, value: str) -> None:
    if not isinstance(value, str) or not value or len(value) > 160 or any(
        char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:-"
        for char in value
    ):
        raise ValueError(f"{name} must be a bounded identifier")


def _digest(name: str, value: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


@dataclass(frozen=True)
class M1Session:
    spec_id: str
    owner_id: str
    state: M1State
    spec: SpecIR | None = None
    clarification_questions: tuple[str, ...] = ()
    unsupported_reason: str | None = None
    frozen_fingerprint: str | None = None

    def validate(self) -> None:
        _id("spec_id", self.spec_id)
        _id("owner_id", self.owner_id)
        if not isinstance(self.state, M1State):
            raise ValueError("state must be an M1State")
        if self.spec is not None:
            self.spec.validate()
        if not all(isinstance(item, str) and item.strip() for item in self.clarification_questions):
            raise ValueError("clarification_questions must contain non-empty text")
        if self.state is M1State.NEEDS_CLARIFICATION and not self.clarification_questions:
            raise ValueError("needs_clarification requires questions")
        if self.state is M1State.UNSUPPORTED_SCOPE and not self.unsupported_reason:
            raise ValueError("unsupported_scope requires a reason")
        if self.state is M1State.FROZEN:
            if self.spec is None or not self.frozen_fingerprint:
                raise ValueError("frozen session requires a spec and fingerprint")
            _digest("frozen_fingerprint", self.frozen_fingerprint)

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "spec_id": self.spec_id,
            "owner_id": self.owner_id,
            "state": self.state.value,
            "spec": self.spec.to_dict() if self.spec is not None else None,
            "clarification_questions": list(self.clarification_questions),
            "unsupported_reason": self.unsupported_reason,
            "frozen_fingerprint": self.frozen_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "M1Session":
        value = dict(payload)
        value["state"] = M1State(value["state"])
        if value.get("spec") is not None:
            value["spec"] = SpecIR.from_dict(value["spec"])
        value["clarification_questions"] = tuple(value.get("clarification_questions", ()))
        result = cls(**value)
        result.validate()
        return result


@dataclass(frozen=True)
class RTLVersion:
    version_id: str
    spec_id: str
    rtl_sha256: str
    generator: str
    verification_status: VerificationStatus = VerificationStatus.NOT_RUN
    verification_run_id: str | None = None
    simulation_status: SimulationStatus = SimulationStatus.NOT_RUN
    simulation_run_id: str | None = None
    parent_version_id: str | None = None
    source_ref: str | None = None

    def validate(self) -> None:
        for name, value in (("version_id", self.version_id), ("spec_id", self.spec_id),
                            ("generator", self.generator)):
            _id(name, value)
        _digest("rtl_sha256", self.rtl_sha256)
        if not isinstance(self.verification_status, VerificationStatus):
            raise ValueError("verification_status must be typed")
        if not isinstance(self.simulation_status, SimulationStatus):
            raise ValueError("simulation_status must be typed")
        if self.verification_run_id is not None:
            _id("verification_run_id", self.verification_run_id)
        if self.simulation_run_id is not None:
            _id("simulation_run_id", self.simulation_run_id)
        if self.parent_version_id is not None:
            _id("parent_version_id", self.parent_version_id)
            if self.parent_version_id == self.version_id:
                raise ValueError("RTLVersion cannot be its own parent")
        if self.source_ref is not None and not self.source_ref.startswith("input:"):
            raise ValueError("source_ref must be a v2 input reference")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "version_id": self.version_id,
            "spec_id": self.spec_id,
            "rtl_sha256": self.rtl_sha256,
            "generator": self.generator,
            "verification_status": self.verification_status.value,
            "verification_run_id": self.verification_run_id,
            "simulation_status": self.simulation_status.value,
            "simulation_run_id": self.simulation_run_id,
            "parent_version_id": self.parent_version_id,
            "source_ref": self.source_ref,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RTLVersion":
        value = dict(payload)
        value["verification_status"] = VerificationStatus(value["verification_status"])
        value["simulation_status"] = SimulationStatus(value.get("simulation_status", "not_run"))
        result = cls(**value)
        result.validate()
        return result
