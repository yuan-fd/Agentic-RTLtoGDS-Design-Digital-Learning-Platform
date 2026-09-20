from __future__ import annotations

import sys
from pathlib import Path

M1_SRC = Path(__file__).parents[1] / "apps/m1_rtl_to_gds/src"
if str(M1_SRC) not in sys.path:
    sys.path.insert(0, str(M1_SRC))

from openroad_app_m1.catalog import course_records, pdk_capabilities  # noqa: E402
from openroad_platform_contracts import CapabilityStatus  # noqa: E402


def test_catalog_contains_ten_complete_course_records():
    records = course_records()
    assert len(records) == 10
    assert {record.exercise.exercise_id for record in records} == {
        "course-mux-decoder", "course-priority-encoder", "course-adder-subtractor",
        "course-alu", "course-edge-detector", "course-counter",
        "course-shift-register", "course-fifo", "course-uart-tx",
        "course-sequence-fsm",
    }
    assert all(record.spec_ref and record.oracle_ref and record.recipe_id for record in records)


def test_catalog_does_not_claim_unsmoked_pdks_available():
    capabilities = pdk_capabilities()
    assert len(capabilities) == 30
    assert all(item.status is not CapabilityStatus.AVAILABLE for item in capabilities)
    assert all(item.reason for item in capabilities if item.pdk_id != "nangate45")
