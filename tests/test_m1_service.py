from __future__ import annotations

import sys
from pathlib import Path

import pytest

M1_SRC = Path(__file__).parents[1] / "apps/m1_rtl_to_gds/src"
if str(M1_SRC) not in sys.path:
    sys.path.insert(0, str(M1_SRC))

from openroad_app_m1.models import M1State, VerificationStatus  # noqa: E402
from openroad_app_m1.service import M1Service  # noqa: E402

from openroad_platform_contracts.rtl_frontend import PortSpec, SpecIR  # noqa: E402


def spec_ir() -> SpecIR:
    return SpecIR(
        spec_id="spec-counter",
        design_id="course-counter",
        top="counter",
        functionality="A synchronous counter with reset and enable.",
        objective="Teach sequential RTL and a bounded RTL-to-GDS flow.",
        ports=(
            PortSpec("clk", "input", 1),
            PortSpec("rst_n", "input", 1),
            PortSpec("enable", "input", 1),
            PortSpec("q", "output", 8),
        ),
        clock="clk",
        reset="rst_n",
        constraints={"clock_period_ns": 5.0},
        acceptance_criteria=("q increments on each enabled rising edge",),
    )


def test_incomplete_spec_can_only_ask_for_clarification() -> None:
    service = M1Service.in_memory()

    session = service.assess_spec("user-1", clarification_questions=("What is the clock?",))

    assert session.state is M1State.NEEDS_CLARIFICATION
    with pytest.raises(ValueError, match="frozen"):
        service.freeze_spec(session.spec_id)


def test_unsupported_scope_never_creates_an_execution_request() -> None:
    service = M1Service.in_memory()

    session = service.assess_spec(
        "user-1", unsupported_reason="multiple clock domains are not supported"
    )

    assert session.state is M1State.UNSUPPORTED_SCOPE
    with pytest.raises(ValueError, match="unsupported_scope"):
        service.freeze_spec(session.spec_id)


def test_editing_rtl_creates_a_new_version_and_invalidates_old_evidence() -> None:
    service = M1Service.in_memory()
    session = service.assess_spec("user-1", spec=spec_ir())
    frozen = service.freeze_spec(session.spec_id)
    first = service.create_rtl_version(
        frozen.spec_id, "module counter; endmodule", "direct_llm", source_ref="input:rtl-1"
    )
    service.record_verification(first.version_id, VerificationStatus.PASSED, "run-verify-1")

    second = service.create_rtl_version(
        frozen.spec_id, "module counter; logic [7:0] q; endmodule", "user_edit",
        parent_version_id=first.version_id,
        source_ref="input:rtl-2",
    )

    assert second.version_id != first.version_id
    assert service.get_rtl_version(first.version_id).verification_status is VerificationStatus.INVALIDATED
    assert service.get_rtl_version(second.version_id).verification_status is VerificationStatus.NOT_RUN
    with pytest.raises(ValueError, match="invalidated"):
        service.record_verification(first.version_id, VerificationStatus.PASSED, "late-run")


def test_unverified_rtl_cannot_submit_rtl_to_gds() -> None:
    service = M1Service.in_memory()
    session = service.assess_spec("user-1", spec=spec_ir())
    frozen = service.freeze_spec(session.spec_id)
    version = service.create_rtl_version(
        frozen.spec_id, "module counter; endmodule", "direct_llm", source_ref="input:rtl-1"
    )

    with pytest.raises(ValueError, match="verification"):
        service.build_rtl_to_gds_request(version.version_id, "nangate45")


def test_verified_request_keeps_the_selected_pdk_and_version() -> None:
    service = M1Service.in_memory()
    session = service.assess_spec("user-1", spec=spec_ir())
    frozen = service.freeze_spec(session.spec_id)
    version = service.create_rtl_version(
        frozen.spec_id, "module counter; endmodule", "direct_llm", source_ref="input:rtl-1"
    )
    service.record_verification(version.version_id, VerificationStatus.PASSED, "run-verify-1")

    request = service.build_rtl_to_gds_request(version.version_id, "sky130hd")

    assert request["parameters"]["pdk"] == "sky130hd"
    assert request["plugin_id"] == "orfs"
    assert request["inputs"]["rtl_path"] == "rtl/counter.sv"
    assert request["parameters"]["rtl_version_id"] == version.version_id
    assert version.version_id in request["design_id"]
    assert request["staged_inputs"][0]["input_id"] == "rtl-1"
    assert request["schema_version"] == 3
    assert request["inputs"]["clock_period_ns"] == 5.0
    assert request["expected_artifacts"] == ["report", "gds", "def", "netlist", "odb"]


def test_clocked_spec_without_a_period_requires_clarification() -> None:
    service = M1Service.in_memory()
    incomplete = SpecIR(
        spec_id="spec-fsm", design_id="course-fsm", top="fsm",
        functionality="a one-clock FSM", objective="teach FSMs",
        ports=(PortSpec("clk", "input", 1), PortSpec("state", "output", 2)),
        clock="clk", acceptance_criteria=("state follows the transition table",),
    )

    session = service.assess_spec("user-1", spec=incomplete)

    assert session.state is M1State.NEEDS_CLARIFICATION
    assert any("period" in question for question in session.clarification_questions)


def test_m1_state_survives_reopening_its_own_database(tmp_path: Path) -> None:
    database = tmp_path / "m1.sqlite"
    first_service = M1Service.open(str(database))
    session = first_service.assess_spec("user-1", spec=spec_ir())
    frozen = first_service.freeze_spec(session.spec_id)
    version = first_service.create_rtl_version(
        frozen.spec_id, "module counter; endmodule", "direct_llm", source_ref="input:rtl-1"
    )
    first_service.store.close()

    second_service = M1Service.open(str(database))

    assert second_service.get_rtl_version(version.version_id).rtl_sha256 == version.rtl_sha256
    assert second_service.get_session(frozen.spec_id).state is M1State.FROZEN
    second_service.store.close()
