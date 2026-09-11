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
    if context is None:
        values = {}
    elif not isinstance(context, dict):
        raise ValueError("teaching context must be an object")
    else:
        values = context
    unknown = set(values) - {"design_id", "objective", "hypothesis"}
    if unknown:
        raise ValueError(f"unknown teaching context fields: {', '.join(sorted(unknown))}")
    if any(value is not None and not isinstance(value, str) for value in values.values()):
        raise ValueError("teaching context values must be strings")
    result = {key: value.strip() for key, value in values.items()
              if value is not None and value.strip()}
    if selected is TeachingMode.GUIDED and result:
        raise ValueError("guided mode does not accept custom design or experiment fields")
    if selected is TeachingMode.CHALLENGE and any(not result.get(key) for key in ("objective", "hypothesis")):
        raise ValueError("challenge mode requires objective and hypothesis")
    return result


TEACHING_MODES = (
    {"id": TeachingMode.GUIDED.value, "label": "Guided Lab", "custom_design": False,
     "custom_objective": True, "requires_hypothesis": False},
    {"id": TeachingMode.OPEN.value, "label": "Open Lab", "custom_design": True,
     "custom_objective": True, "requires_hypothesis": False},
    {"id": TeachingMode.CHALLENGE.value, "label": "Challenge", "custom_design": True,
     "custom_objective": True, "requires_hypothesis": True},
)
