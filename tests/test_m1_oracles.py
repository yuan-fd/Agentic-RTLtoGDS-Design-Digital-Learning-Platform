from __future__ import annotations

import sys
from pathlib import Path

M1_SRC = Path(__file__).parents[1] / "apps/m1_rtl_to_gds/src"
if str(M1_SRC) not in sys.path:
    sys.path.insert(0, str(M1_SRC))

from openroad_app_m1.oracles import oracle_for_top  # noqa: E402


def test_counter_oracle_covers_hold_overflow_and_reset():
    package = oracle_for_top("counter")
    assert package is not None
    _, source, top = package
    assert top == "counter_tb"
    assert "disabled counter changed" in source
    assert "overflow mismatch" in source
    assert "reset priority mismatch" in source


def test_sequence_oracle_covers_negative_and_overlapping_sequences():
    package = oracle_for_top("sequence_detector")
    assert package is not None
    _, source, top = package
    assert top == "sequence_detector_tb"
    assert source.count("tick(") >= 10
    assert "sequence mismatch" in source


def test_unknown_top_has_no_teaching_oracle():
    assert oracle_for_top("arbitrary_design") is None
