import pytest

from openroad_platform_contracts import TeachingMode, validate_teaching_mode, TEACHING_MODES, validate_teaching_request


def test_teaching_modes_are_bounded_and_normalized():
    assert validate_teaching_mode(" Open ") is TeachingMode.OPEN
    assert [item["id"] for item in TEACHING_MODES] == ["guided", "open", "challenge"]
    with pytest.raises(ValueError, match="guided, open, or challenge"):
        validate_teaching_mode("terminal")

def test_teaching_request_applies_mode_specific_gates():
    assert validate_teaching_request("open", {"design_id": "uart", "objective": "area"})["design_id"] == "uart"
    with pytest.raises(ValueError, match="hypothesis"):
        validate_teaching_request("challenge", {"objective": "area"})
    with pytest.raises(ValueError, match="guided"):
        validate_teaching_request("guided", {"design_id": "uart"})
