"""Contracts owned by the teaching product layer.

The execution plane deliberately knows nothing about these records.  They are
the stable boundary used by the teaching modules when they describe exercises,
PDK readiness, and user-approved recipe changes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from .platform import (
    SCHEMA_VERSION,
    _known_payload,
    _primitive,
    _validate_identifier,
    _validate_version,
)


class CapabilityStatus(str, Enum):
    REGISTERED = "registered"
    TOOLCHAIN_READY = "toolchain_ready"
    RECIPE_READY = "recipe_ready"
    RTL_SMOKE_PASSED = "rtl_smoke_passed"
    GDS_SMOKE_PASSED = "gds_smoke_passed"
    AVAILABLE = "available"
    BLOCKED = "blocked"


_PATH_PART = re.compile(r"^[A-Za-z0-9._-]+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _text(name: str, value: str, maximum: int = 4000) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{name} must be non-empty text up to {maximum} characters")


def _ref(name: str, value: str, prefix: str) -> None:
    _text(name, value, maximum=256)
    if not value.startswith(prefix):
        raise ValueError(f"{name} must be a {prefix} reference")


def _digest(name: str, value: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


@dataclass(frozen=True)
class CourseExercise:
    exercise_id: str
    title: str
    category: str
    level: str
    description: str
    supported_pdks: tuple[str, ...]
    verification_id: str
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        _validate_identifier("exercise_id", self.exercise_id)
        _validate_identifier("verification_id", self.verification_id)
        for name, value in (("title", self.title), ("category", self.category),
                            ("level", self.level), ("description", self.description)):
            _text(name, value)
        if not self.supported_pdks or not isinstance(self.supported_pdks, tuple):
            raise ValueError("supported_pdks must be a non-empty tuple")
        for pdk in self.supported_pdks:
            _validate_identifier("supported_pdk", pdk)
        if len(set(self.supported_pdks)) != len(self.supported_pdks):
            raise ValueError("supported_pdks must be unique")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CourseExercise":
        value = _known_payload(cls, payload)
        value["supported_pdks"] = tuple(value.get("supported_pdks", ()))
        result = cls(**value)
        result.validate()
        return result


@dataclass(frozen=True)
class CourseLabRecord:
    exercise: CourseExercise
    spec_ref: str
    reference_rtl_ref: str
    oracle_ref: str
    recipe_id: str
    teaching_notes: str
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        self.exercise.validate()
        _ref("spec_ref", self.spec_ref, "spec:")
        _ref("reference_rtl_ref", self.reference_rtl_ref, "source:")
        _ref("oracle_ref", self.oracle_ref, "source:")
        _validate_identifier("recipe_id", self.recipe_id)
        _text("teaching_notes", self.teaching_notes)

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)


@dataclass(frozen=True)
class PdkCapability:
    exercise_id: str
    pdk_id: str
    status: CapabilityStatus
    recipe_id: str
    reason: str | None = None
    smoke_evidence_id: str | None = None
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        _validate_identifier("exercise_id", self.exercise_id)
        _validate_identifier("pdk_id", self.pdk_id)
        _validate_identifier("recipe_id", self.recipe_id)
        if not isinstance(self.status, CapabilityStatus):
            raise ValueError("status must be a CapabilityStatus")
        if self.reason is not None:
            _text("reason", self.reason, maximum=2000)
        if self.smoke_evidence_id is not None:
            _ref("smoke_evidence_id", self.smoke_evidence_id, "evidence:")
        if self.status is CapabilityStatus.BLOCKED and not self.reason:
            raise ValueError("blocked capability requires a reason")
        if self.status is CapabilityStatus.GDS_SMOKE_PASSED and not self.smoke_evidence_id:
            raise ValueError("gds_smoke_passed capability requires smoke evidence")
        if self.status is CapabilityStatus.AVAILABLE and not self.smoke_evidence_id:
            raise ValueError("available capability requires smoke evidence")

    @property
    def available(self) -> bool:
        self.validate()
        return self.status in {CapabilityStatus.GDS_SMOKE_PASSED, CapabilityStatus.AVAILABLE}

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PdkCapability":
        value = _known_payload(cls, payload)
        if isinstance(value.get("status"), str):
            value["status"] = CapabilityStatus(value["status"])
        result = cls(**value)
        result.validate()
        return result


def _relative_allowed_path(path: str) -> None:
    if not isinstance(path, str) or not path or path.startswith(("/", "\\")):
        raise ValueError("allowed_paths must contain a relative allowed path")
    if "\\" in path or ".." in path.split("/"):
        raise ValueError("allowed_paths must contain a relative allowed path")
    if not all(_PATH_PART.fullmatch(part) for part in path.split("/")):
        raise ValueError("allowed_paths must contain a relative allowed path")


def _patch_paths(patch: str) -> set[str]:
    paths: set[str] = set()
    for line in patch.splitlines():
        if not line.startswith(("--- ", "+++ ")):
            continue
        raw = line[4:].split("\t", 1)[0].split(" ", 1)[0]
        if raw == "/dev/null":
            continue
        if raw.startswith(("a/", "b/")):
            raw = raw[2:]
        _relative_allowed_path(raw)
        paths.add(raw)
    if not paths:
        raise ValueError("patch must contain unified diff file paths")
    return paths


@dataclass(frozen=True)
class ScriptProposal:
    proposal_id: str
    owner_id: str
    entrypoint_id: str
    base_recipe_digest: str
    patch: str
    allowed_paths: tuple[str, ...]
    requires_confirmation: bool
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        for name, value in (("proposal_id", self.proposal_id), ("owner_id", self.owner_id),
                            ("entrypoint_id", self.entrypoint_id)):
            _validate_identifier(name, value)
        _digest("base_recipe_digest", self.base_recipe_digest)
        _text("patch", self.patch, maximum=200_000)
        if not isinstance(self.allowed_paths, tuple) or not self.allowed_paths:
            raise ValueError("allowed_paths must be a non-empty tuple")
        for path in self.allowed_paths:
            _relative_allowed_path(path)
        if len(set(self.allowed_paths)) != len(self.allowed_paths):
            raise ValueError("allowed_paths must be unique")
        if not _patch_paths(self.patch).issubset(set(self.allowed_paths)):
            raise ValueError("patch modifies a path outside allowed_paths")
        if self.requires_confirmation is not True:
            raise ValueError("script proposal requires explicit confirmation")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ScriptProposal":
        value = _known_payload(cls, payload)
        value["allowed_paths"] = tuple(value.get("allowed_paths", ()))
        result = cls(**value)
        result.validate()
        return result
