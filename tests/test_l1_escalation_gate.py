"""The L1→L2 escalation gate is visible, typed, and never auto-submits."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from openroad_platform_contracts import PluginManifest
from openroad_platform_contracts.l1_observation import RuntimeObservation
from openroad_platform_contracts.learning import EvidencePointer
from openroad_platform_scheduler.l1_state_reducer import L1StateReducer

sys.path.insert(0, str(Path(__file__).parents[1] / "apps" / "l1_workbench"))

import service as workbench_module  # noqa: E402
from service import WorkbenchService  # noqa: E402


def test_escalation_gate_requires_the_real_orfs_backend(tmp_path):
    service = WorkbenchService(tmp_path, backend="smoke")
    with pytest.raises(ValueError, match="ORFS"):
        service.l2_escalate("l1-session-unused")


def test_terminal_exposes_the_l2_authorization_command():
    source = (Path(__file__).parents[1] / "apps/l1_workbench/terminal_dashboard.py").read_text()
    assert ":l2" in source
    assert "/l2-escalate" in source


def test_service_route_is_exposed_by_the_thin_http_server():
    source = (Path(__file__).parents[1] / "apps/l1_workbench/server.py").read_text()
    assert 'l2-escalate' in source


def test_repeated_escalation_of_one_observed_state_returns_one_controller(tmp_path, monkeypatch):
    rtl = tmp_path / "top.v"
    rtl.write_text("module top; endmodule\n", encoding="utf-8")
    toolchain = SimpleNamespace(name="test-toolchain", validate=lambda: None)
    monkeypatch.setattr(
        workbench_module.ToolchainConfig, "from_environment",
        classmethod(lambda cls, **_kwargs: toolchain),
    )
    orfs_manifest = PluginManifest(
        plugin_id="orfs", plugin_version="1", adapter_entry=("unused",),
        capabilities=("eda.rtl_to_gds",), supported_arch=(workbench_module.platform.machine(),),
        input_schema={"type": "object"}, output_schema={"type": "object"},
    )
    monkeypatch.setattr(workbench_module, "orfs_plugin_manifest",
                        lambda *_args, **_kwargs: orfs_manifest)
    source = Path(__file__).parents[1] / "var/external-sources/orfs-agent-730f1fa-clean-20260901"
    service = WorkbenchService(
        tmp_path / "state", backend="orfs", rtl=rtl, top="top",
        orfs_agent_source=source,
    )
    started = service.start("Optimize the managed design with bounded EDA runs.")
    values = {
        "objective": "timing", "constraints": "drc_zero_area_plus_3pct",
        "clock_sdc": "protect_clock_sdc", "change_scope": "registered_parameters_only",
        "budget": "3", "design_context": "managed_mux_default_corner_baseline",
    }
    draft, _ = service.sessions.store.draft_and_policy(started.session_id)
    finalized = service.answer(started.session_id, [
        {"question_id": question.question_id, "field": question.field.value,
         "value": values[question.question_id]}
        for question in draft.questions if question.blocking
    ])
    state, _ = service._load(finalized.session_id)
    goal = service._goal(finalized.trace_id, finalized.goal_id)
    for index in range(2):
        observation = RuntimeObservation(
            f"run-{index}", f"attempt-{index}", "finish", "succeeded",
            {"setup_wns_ns": 0.1 + index * .01},
            (EvidencePointer(f"artifact:official-{index}", str(index + 1) * 64),),
        )
        successor = L1StateReducer.apply(
            state, observation, next_state_id=f"state-{index}", consume_eda_run=True)
        service.trace.record_observation(
            finalized.trace_id, state, successor, observation, consume_eda_run=True)
        state = successor
    service._save(finalized.session_id, state, None)

    first = service.l2_escalate(finalized.session_id)
    second = service.l2_escalate(finalized.session_id)

    assert first["pipeline_id"] == second["pipeline_id"]
    assert first["authorization"] == second["authorization"]
    assert first["request"] == second["request"]
    assert first["pipeline_status"] == "authorized"
    assert first["request"]["plugin_id"] == "a2-orfo"
    assert first["request"]["capability"] == "optimizer.l2.a2-orfo-feedback"
