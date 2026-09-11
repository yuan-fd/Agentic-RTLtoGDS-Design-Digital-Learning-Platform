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

def validate_teaching_request(mode: str, context: dict | None = None) -> dict[str, str]:
    selected = validate_teaching_mode(mode)
    values = dict(context or {})
    unknown = set(values) - {"design_id", "objective", "hypothesis"}
    if unknown:
        raise ValueError(f"unknown teaching context fields: {', '.join(sorted(unknown))}")
    result = {key: str(value).strip() for key, value in values.items()
              if value is not None and str(value).strip()}
    if selected is TeachingMode.GUIDED and result:
        raise ValueError("guided mode does not accept custom design or experiment fields")
    if selected is TeachingMode.OPEN and "hypothesis" in result:
        raise ValueError("open mode accepts a design and objective; use challenge for a hypothesis")
    if selected is TeachingMode.CHALLENGE and any(not result.get(key) for key in ("objective", "hypothesis")):
        raise ValueError("challenge mode requires objective and hypothesis")
    return result


TEACHING_MODES = (
    {"id": TeachingMode.GUIDED.value, "label": "Guided Lab", "custom_design": False,
     "custom_objective": False, "requires_hypothesis": False},
    {"id": TeachingMode.OPEN.value, "label": "Open Lab", "custom_design": True,
     "custom_objective": False, "requires_hypothesis": False},
    {"id": TeachingMode.CHALLENGE.value, "label": "Challenge", "custom_design": True,
     "custom_objective": True, "requires_hypothesis": True},
)
