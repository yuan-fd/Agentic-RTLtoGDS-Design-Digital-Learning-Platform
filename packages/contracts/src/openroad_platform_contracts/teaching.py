"""Small public contract for the teaching experiment modes."""
from __future__ import annotations

from enum import Enum


class TeachingMode(str, Enum):
    GUIDED = "guided"
    OPEN = "open"
    CHALLENGE = "challenge"


def validate_teaching_mode(value: str) -> TeachingMode:
    """Normalize a user mode and reject unknown execution policies."""
    try:
        return TeachingMode(str(value).strip().lower())
    except ValueError as exc:
        raise ValueError("teaching mode must be guided, open, or challenge") from exc


TEACHING_MODES = (
    {"id": TeachingMode.GUIDED.value, "label": "Guided Lab", "custom_design": False,
     "custom_objective": False, "requires_hypothesis": False},
    {"id": TeachingMode.OPEN.value, "label": "Open Lab", "custom_design": True,
     "custom_objective": False, "requires_hypothesis": False},
    {"id": TeachingMode.CHALLENGE.value, "label": "Challenge", "custom_design": True,
     "custom_objective": True, "requires_hypothesis": True},
)
