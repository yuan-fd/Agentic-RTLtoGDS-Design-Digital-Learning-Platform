from __future__ import annotations

import pytest

from openroad_platform_contracts import AgentBudget, EvidencePointer, PortSpec
from openroad_platform_scheduler.design_goal_compiler import (
    compile_design_goal, infer_goal_preference,
)
from openroad_platform_scheduler.spec_conversation import SpecProposal


def _proposal(*, ready=True):
    return SpecProposal(
        objective="以面积优先完成 UART", functionality="UART transmitter",
        top="uart_tx", clock="clk", reset="rst_n", target_platform="asap7",
        target_stage="finish", clock_period_ns=10, core_utilization_pct=30,
        place_density=.55, ports=(PortSpec("clk", "input", 1),
                                  PortSpec("tx", "output", 1)),
        missing_fields=(), assumptions=(), clarification_questions=(),
        ready_for_execution=ready,
    )


def test_compiler_turns_admitted_spec_result_into_typed_goal():
    goal = compile_design_goal(
        goal_id="goal-1", project_id="project-1", design_id="uart",
        proposal=_proposal(), rtl_artifact=EvidencePointer("artifact:rtl", "a" * 64),
        pdk_id="asap7", toolchain_id="orfs-pinned",
        allowed_parameters=("core_utilization_pct", "cts_cluster_size"),
        budget=AgentBudget(20, 10, 3600, 2),
    )
    assert goal.preference.value == "area"
    assert goal.allowed_stages[-1] == "finish"
    assert {item.metric for item in goal.hard_constraints} == {"setup_wns_ns", "drc_errors"}


def test_compiler_refuses_incomplete_spec_and_preference_is_transparent():
    with pytest.raises(ValueError, match="incomplete"):
        compile_design_goal(
            goal_id="goal-1", project_id="project-1", design_id="uart", proposal=_proposal(ready=False),
            rtl_artifact=EvidencePointer("artifact:rtl", "a" * 64), pdk_id="asap7",
            toolchain_id="orfs-pinned", allowed_parameters=("core_utilization_pct",),
            budget=AgentBudget(20, 10, 3600, 2))
    assert infer_goal_preference("平衡 PPA") .value == "balanced"
    assert infer_goal_preference("重点是时序") .value == "performance"
