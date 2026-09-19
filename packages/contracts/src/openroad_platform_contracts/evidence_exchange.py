"""Minimal metadata-only exchange contract between teaching modules and v2."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from .platform import SCHEMA_VERSION, _known_payload, _primitive, _validate_identifier, _validate_version


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _digest(name: str, value: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _ref(name: str, value: str, prefix: str) -> None:
    if not isinstance(value, str) or not value.startswith(prefix) or len(value) > 256:
        raise ValueError(f"{name} must be a {prefix} reference")


@dataclass(frozen=True)
class EvidenceRef:
    evidence_id: str
    owner_id: str
    spec_id: str
    candidate_id: str
    run_id: str
    artifact_ids: tuple[str, ...]
    evidence_kind: str
    status: str
    sha256: str
    toolchain_digest: str
    protocol_digest: str
    claim_boundary: str
    created_at: str
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        for name, value in (("evidence_id", self.evidence_id), ("owner_id", self.owner_id),
                            ("spec_id", self.spec_id), ("candidate_id", self.candidate_id),
                            ("run_id", self.run_id), ("evidence_kind", self.evidence_kind)):
            _validate_identifier(name, value)
        if not isinstance(self.artifact_ids, tuple) or not self.artifact_ids:
            raise ValueError("artifact_ids must be a non-empty tuple")
        for artifact_id in self.artifact_ids:
            _ref("artifact_id", artifact_id, "artifact:")
        if len(set(self.artifact_ids)) != len(self.artifact_ids):
            raise ValueError("artifact_ids must be unique")
        if self.status not in {"pending", "succeeded", "failed", "incomplete", "rejected"}:
            raise ValueError("unsupported evidence status")
        for name, value in (("sha256", self.sha256), ("toolchain_digest", self.toolchain_digest),
                            ("protocol_digest", self.protocol_digest)):
            _digest(name, value)
        if not isinstance(self.claim_boundary, str) or not self.claim_boundary.strip() or len(self.claim_boundary) > 4000:
            raise ValueError("claim_boundary must be non-empty bounded text")
        try:
            parsed = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise ValueError("created_at must be ISO-8601") from exc
        if parsed.tzinfo is None:
            raise ValueError("created_at must include a timezone")
        if self.status == "succeeded" and not self.artifact_ids:
            raise ValueError("succeeded evidence requires artifacts")

    @property
    def complete(self) -> bool:
        self.validate()
        return self.status == "succeeded"

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return _primitive(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EvidenceRef":
        value = _known_payload(cls, payload)
        value["artifact_ids"] = tuple(value.get("artifact_ids", ()))
        result = cls(**value)
        result.validate()
        return result
