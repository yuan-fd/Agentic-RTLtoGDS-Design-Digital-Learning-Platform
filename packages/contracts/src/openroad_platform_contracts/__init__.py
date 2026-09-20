"""Contracts used by the independent teaching applications."""

from .evidence_exchange import EvidenceRef
from .rtl_frontend import PortSpec, RTLCandidate, SpecIR, VerificationPackage
from .teaching_catalog import (
    CapabilityStatus,
    CourseExercise,
    CourseLabRecord,
    PdkCapability,
    ScriptProposal,
)

__all__ = [
    "CapabilityStatus",
    "CourseExercise",
    "CourseLabRecord",
    "EvidenceRef",
    "PdkCapability",
    "PortSpec",
    "RTLCandidate",
    "ScriptProposal",
    "SpecIR",
    "VerificationPackage",
]
