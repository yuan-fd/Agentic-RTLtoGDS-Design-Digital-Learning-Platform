"""Capability-level task construction contracts.

The Scheduler may ask for a typed capability task but must not import a
concrete implementation such as ORFS.  Concrete plugins implement this port at
the integration boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from .platform import IDENTIFIER, TaskSpec


RTL_TO_GDS_CAPABILITY = "eda.rtl_to_gds"
OPENROAD_KNOWLEDGE_CAPABILITY = "knowledge.openroad.retrieve"


@dataclass(frozen=True)
class RTLToGDSRequest:
    """A capability request for an already admitted RTL artifact.

    ``options`` remain capability-private.  The shared contract validates only
    transport-safe shape; the selected factory validates its own allowlist and
    maps options to the upstream plugin's native configuration.
    """

    rtl_path: str
    project_id: str
    design_id: str
    top: str | None = None
    task_id: str | None = None
    labels: dict[str, str] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    capability: str = RTL_TO_GDS_CAPABILITY

    def validate(self) -> None:
        if not isinstance(self.rtl_path, str) or not self.rtl_path:
            raise ValueError("rtl_path must be a non-empty string")
        for name, value, required in (
            ("project_id", self.project_id, True),
            ("design_id", self.design_id, True),
            ("top", self.top, False),
            ("task_id", self.task_id, False),
            ("capability", self.capability, True),
        ):
            if value is None and not required:
                continue
            if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
                raise ValueError(f"Invalid {name}: {value!r}")
        if not isinstance(self.labels, Mapping) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in self.labels.items()
        ):
            raise ValueError("labels must be a string-to-string mapping")
        if not isinstance(self.options, Mapping) or not all(
            isinstance(key, str) for key in self.options
        ):
            raise ValueError("options must be a string-keyed mapping")


class RTLToGDSFactory(Protocol):
    """Port used by Scheduler for RTL-to-GDS task creation and updates."""

    capability: str

    def build(self, request: RTLToGDSRequest) -> TaskSpec:
        """Build one validated TaskSpec for the advertised capability."""

    def validate_task(self, task: TaskSpec) -> None:
        """Reject a TaskSpec that does not belong to this factory."""

    def reconfigure(self, task: TaskSpec, values: Mapping[str, Any]) -> TaskSpec:
        """Validate a bounded typed parameter update without executing it."""


@dataclass(frozen=True)
class KnowledgeQueryRequest:
    """Bounded request for cited OpenROAD knowledge, never an EDA command."""

    project_id: str
    design_id: str
    query: str
    purpose: str = "knowledge"
    top_k: int = 5
    task_id: str | None = None
    labels: dict[str, str] = field(default_factory=dict)
    capability: str = OPENROAD_KNOWLEDGE_CAPABILITY

    def validate(self) -> None:
        for name, value, required in (
            ("project_id", self.project_id, True),
            ("design_id", self.design_id, True),
            ("task_id", self.task_id, False),
            ("capability", self.capability, True),
        ):
            if value is None and not required:
                continue
            if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
                raise ValueError(f"Invalid {name}: {value!r}")
        if self.capability != OPENROAD_KNOWLEDGE_CAPABILITY:
            raise ValueError("knowledge request capability is fixed")
        if (not isinstance(self.query, str) or not self.query.strip()
                or len(self.query.encode("utf-8")) > 16_384 or "\x00" in self.query):
            raise ValueError("knowledge query must be bounded non-empty UTF-8 text")
        if self.purpose not in {"knowledge", "error_explanation"}:
            raise ValueError("knowledge purpose is unsupported")
        if (isinstance(self.top_k, bool) or not isinstance(self.top_k, int)
                or not 1 <= self.top_k <= 10):
            raise ValueError("knowledge top_k must be between 1 and 10")
        if not isinstance(self.labels, Mapping) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in self.labels.items()
        ):
            raise ValueError("knowledge labels must be a string mapping")


class KnowledgeTaskFactory(Protocol):
    """Plugin-neutral Scheduler port for an admitted knowledge capability."""

    capability: str

    def build(self, request: KnowledgeQueryRequest) -> TaskSpec:
        """Build one immutable knowledge TaskSpec."""

    def validate_task(self, task: TaskSpec) -> None:
        """Reject a task outside the selected knowledge plugin boundary."""
