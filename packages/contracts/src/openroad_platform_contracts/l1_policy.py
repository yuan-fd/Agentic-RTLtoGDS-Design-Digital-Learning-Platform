"""Trusted policy identity carried into durable L1 audit records."""

from __future__ import annotations

from dataclasses import dataclass

from .learning import EvidencePointer
from .platform import SCHEMA_VERSION, _primitive, _validate_identifier, _validate_version


@dataclass(frozen=True)
class TrustedPolicyIdentity:
    policy_id: str
    policy_version: str
    issuer: str
    provenance: EvidencePointer
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        _validate_version(self.schema_version)
        for name, value in (("policy_id", self.policy_id), ("policy_version", self.policy_version), ("issuer", self.issuer)):
            _validate_identifier(name, value)
        self.provenance.validate()

    def to_dict(self) -> dict:
        self.validate()
        return _primitive(self)
