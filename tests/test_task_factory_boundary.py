from __future__ import annotations

import pytest

from openroad_platform_contracts import RTLToGDSRequest
from openroad_platform_execution import ORFSRTLToGDSFactory, build_orfs_task


def test_orfs_factory_preserves_frozen_builder_fields(tmp_path):
    rtl = tmp_path / "top.v"
    rtl.write_text("module top(input a, output y); assign y = a; endmodule\n", encoding="utf-8")
    options = {
        "platform_name": "nangate45", "target_stage": "finish",
        "clock_period_ns": 8.0, "core_utilization_pct": 35.0,
        "place_density": 0.55, "or_seed": 123,
        "stage_timeout_seconds": 77, "timeout_seconds": 88,
    }
    expected = build_orfs_task(
        rtl, project_id="p1", design_id="top", top="top", task_id="frozen-task",
        labels={"source": "fixture"}, **options,
    )
    actual = ORFSRTLToGDSFactory().build(RTLToGDSRequest(
        rtl_path=str(rtl), project_id="p1", design_id="top", top="top",
        task_id="frozen-task", labels={"source": "fixture"}, options=options,
    ))
    assert actual.to_dict() == expected.to_dict()


def test_orfs_factory_rejects_unknown_options_and_invalid_task(tmp_path):
    rtl = tmp_path / "top.v"; rtl.write_text("module top; endmodule\n", encoding="utf-8")
    factory = ORFSRTLToGDSFactory()
    with pytest.raises(ValueError, match="Unsupported ORFS task options"):
        factory.build(RTLToGDSRequest(
            rtl_path=str(rtl), project_id="p1", design_id="top",
            options={"shell": "bad"},
        ))
    with pytest.raises(ValueError, match="Unsupported capability"):
        factory.build(RTLToGDSRequest(
            rtl_path=str(rtl), project_id="p1", design_id="top",
            capability="eda.not-admitted",
        ))


def test_orfs_factory_reconfiguration_keeps_the_allowlist_below_scheduler(tmp_path):
    rtl = tmp_path / "top.v"; rtl.write_text("module top; endmodule\n", encoding="utf-8")
    factory = ORFSRTLToGDSFactory()
    task = factory.build(RTLToGDSRequest(
        rtl_path=str(rtl), project_id="p1", design_id="top",
    ))
    changed = factory.reconfigure(task, {"core_utilization_pct": 20.0})
    assert changed.parameters["core_utilization_pct"] == 20.0
    with pytest.raises(ValueError):
        factory.reconfigure(task, {"shell": "bad"})
