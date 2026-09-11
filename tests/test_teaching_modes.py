import pytest

from openroad_platform_contracts import TeachingMode, validate_teaching_mode, TEACHING_MODES


def test_teaching_modes_are_bounded_and_normalized():
    assert validate_teaching_mode(" Open ") is TeachingMode.OPEN
    assert [item["id"] for item in TEACHING_MODES] == ["guided", "open", "challenge"]
    with pytest.raises(ValueError, match="guided, open, or challenge"):
        validate_teaching_mode("terminal")
