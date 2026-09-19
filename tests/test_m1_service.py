from __future__ import annotations

import sys
from pathlib import Path

import pytest

M1_SRC = Path(__file__).parents[1] / "apps/m1_rtl_to_gds/src"
if str(M1_SRC) not in sys.path:
    sys.path.insert(0, str(M1_SRC))

from openroad_app_m1.models import M1State, SimulationStatus, VerificationStatus  # noqa: E402
from openroad_app_m1.service import M1Service  # noqa: E402

from openroad_platform_contracts.rtl_frontend import (  # noqa: E402
    PortSpec,
    SpecIR,
    VerificationPackage,
)
from openroad_platform_contracts.evidence_exchange import EvidenceRef  # noqa: E402


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
        service.build_rtl_to_gds_request(version.version_id, "nangate45", _Plugins([]))


def test_verified_request_keeps_the_selected_pdk_and_version() -> None:
    service = M1Service.in_memory()
    session = service.assess_spec("user-1", spec=spec_ir())
    frozen = service.freeze_spec(session.spec_id)
    version = service.create_rtl_version(
        frozen.spec_id, "module counter; endmodule", "direct_llm", source_ref="input:rtl-1"
    )
    service.record_verification(version.version_id, VerificationStatus.PASSED, "run-verify-1")
    service.record_simulation(version.version_id, SimulationStatus.PASSED, "run-sim-1")
    service.register_verification_package(
        frozen.spec_id,
        VerificationPackage(
            verification_id="verify-counter-v1",
            spec_id=frozen.spec_id,
            compile_checks=("verilator-lint", "yosys-check"),
            simulation_oracle_refs=("artifact:oracle-counter-v1",),
            simulation_top="counter_tb",
            coverage_targets={"mutation_score": 0.8},
        ),
    )

    request = service.build_rtl_to_gds_request(
        version.version_id, "nangate45",
        _Plugins([{"plugin_id": "orfs", "executable": True,
                   "admission": "admitted", "capabilities": ["eda.rtl_to_gds"]}]),
    )

    assert request["parameters"]["pdk"] == "nangate45"
    assert request["plugin_id"] == "orfs"
    assert request["inputs"]["rtl_path"] == "inputs/counter.sv"
    assert request["inputs"]["design"] == "course-counter"
    assert request["inputs"]["orfs_root"] == "/share/home/yuanwenjie/OpenROAD-flow-scripts"
    assert request["inputs"]["openroad_bin"] == "/share/home/yuanwenjie/bin/openroad"
    assert request["inputs"]["yosys_bin"] == "/share/home/yuanwenjie/bin/yosys"
    assert request["inputs"]["klayout_bin"] == "/share/home/yuanwenjie/bin/klayout"
    assert request["inputs"]["stage_timeout_seconds"] == 7200
    assert request["parameters"]["rtl_version_id"] == version.version_id
    assert version.version_id in request["design_id"]
    assert request["staged_inputs"][0]["input_id"] == "rtl-1"
    assert request["resources"] == {"cpu_cores": 4, "memory_bytes": 8589934592, "processes": 256}
    assert request["schema_version"] == 3
    assert request["inputs"]["clock_period_ns"] == 5.0
    assert request["inputs"]["verification_id"] == "verify-counter-v1"
    assert request["expected_artifacts"] == ["gds", "odb", "def", "netlist", "report"]


def test_rtl_to_gds_requires_an_admitted_orfs_toolkit() -> None:
    service = M1Service.in_memory()
    session = service.assess_spec("user-1", spec=spec_ir())
    frozen = service.freeze_spec(session.spec_id)
    service.register_verification_package(
        frozen.spec_id,
        VerificationPackage(
            verification_id="verify-counter-v1", spec_id=frozen.spec_id,
            compile_checks=("verilator-lint",),
            simulation_oracle_refs=("artifact:oracle-counter-v1",),
            simulation_top="counter_tb",
        ),
    )
    version = service.create_rtl_version(
        frozen.spec_id, "module counter; endmodule", "direct_llm", source_ref="input:rtl-1"
    )
    service.record_verification(version.version_id, VerificationStatus.PASSED, "run-verify-1")
    service.record_simulation(version.version_id, SimulationStatus.PASSED, "run-sim-1")

    with pytest.raises(ValueError, match="orfs.*admitted"):
        service.build_rtl_to_gds_request(version.version_id, "nangate45", _Plugins([]))


def test_rtl_to_gds_requires_passed_simulation() -> None:
    service = M1Service.in_memory()
    session = service.assess_spec("user-1", spec=spec_ir())
    frozen = service.freeze_spec(session.spec_id)
    service.register_verification_package(
        frozen.spec_id,
        VerificationPackage(
            verification_id="verify-counter-v1", spec_id=frozen.spec_id,
            compile_checks=("verilator-lint",),
            simulation_oracle_refs=("artifact:oracle-counter-v1",),
            simulation_top="counter_tb",
        ),
    )
    version = service.create_rtl_version(
        frozen.spec_id, "module counter; endmodule", "direct_llm", source_ref="input:rtl-1"
    )
    service.record_verification(version.version_id, VerificationStatus.PASSED, "run-verify-1")

    with pytest.raises(ValueError, match="simulation"):
        service.build_rtl_to_gds_request(
            version.version_id, "nangate45",
            _Plugins([{"plugin_id": "orfs", "executable": True,
                       "admission": "admitted", "capabilities": ["eda.rtl_to_gds"]}]),
        )


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


def test_passed_rtl_without_a_frozen_verification_package_cannot_submit() -> None:
    service = M1Service.in_memory()
    session = service.assess_spec("user-1", spec=spec_ir())
    frozen = service.freeze_spec(session.spec_id)
    version = service.create_rtl_version(
        frozen.spec_id, "module counter; endmodule", "direct_llm", source_ref="input:rtl-1"
    )
    service.record_verification(version.version_id, VerificationStatus.PASSED, "run-verify-1")

    with pytest.raises(ValueError, match="VerificationPackage"):
        service.build_rtl_to_gds_request(version.version_id, "nangate45", _Plugins([]))


def test_verification_submission_requires_an_admitted_v2_toolkit() -> None:
    service = M1Service.in_memory()
    session = service.assess_spec("user-1", spec=spec_ir())
    frozen = service.freeze_spec(session.spec_id)
    service.register_verification_package(
        frozen.spec_id,
        VerificationPackage(
            verification_id="verify-counter-v1",
            spec_id=frozen.spec_id,
            compile_checks=("verilator-lint", "yosys-check"),
            simulation_oracle_refs=("artifact:oracle-counter-v1",),
            simulation_top="counter_tb",
        ),
    )
    version = service.create_rtl_version(
        frozen.spec_id, "module counter; endmodule", "direct_llm", source_ref="input:rtl-1"
    )

    with pytest.raises(ValueError, match="admitted"):
        service.build_verification_request(version.version_id, _Plugins([]))

    task = service.build_verification_request(
        version.version_id, _Plugins([{"plugin_id": "rtl-verify", "executable": True,
                                      "admission": "admitted", "capabilities": ["eda.rtl.verify"]}])
    )

    assert task["plugin_id"] == "rtl-verify"
    assert task["staged_inputs"][0]["input_id"] == "rtl-1"
    assert task["inputs"]["verification_id"] == "verify-counter-v1"


def test_simulation_submission_binds_the_frozen_oracle_artifact() -> None:
    service = M1Service.in_memory()
    session = service.assess_spec("user-1", spec=spec_ir())
    frozen = service.freeze_spec(session.spec_id)
    service.register_verification_package(
        frozen.spec_id,
        VerificationPackage(
            verification_id="verify-counter-v1",
            spec_id=frozen.spec_id,
            compile_checks=("verilator-lint", "yosys-check"),
            simulation_oracle_refs=("artifact:oracle-counter-v1",),
            simulation_top="counter_tb",
        ),
    )
    version = service.create_rtl_version(
        frozen.spec_id, "module counter; endmodule", "direct_llm", source_ref="input:rtl-1"
    )
    service.record_verification(version.version_id, VerificationStatus.PASSED, "run-verify-1")

    task = service.build_simulation_request(
        version.version_id,
        _Plugins([{"plugin_id": "rtl-sim", "executable": True,
                   "admission": "admitted", "capabilities": ["eda.rtl.simulate"]}]),
    )

    assert task["plugin_id"] == "rtl-sim"
    assert task["staged_inputs"] == [
        {"destination": "rtl/counter.sv", "input_id": "rtl-1", "required": True},
        {"destination": "verification/oracle.sv", "artifact_id": "oracle-counter-v1", "required": True},
    ]
    assert task["expected_artifacts"] == ["simulation_report", "log"]


def test_gds_evidence_is_registered_only_for_the_matching_verified_candidate() -> None:
    service = M1Service.in_memory()
    session = service.assess_spec("user-1", spec=spec_ir())
    frozen = service.freeze_spec(session.spec_id)
    service.register_verification_package(
        frozen.spec_id,
        VerificationPackage(
            verification_id="verify-counter-v1", spec_id=frozen.spec_id,
            compile_checks=("verilator-lint",),
            simulation_oracle_refs=("artifact:oracle-counter-v1",),
            simulation_top="counter_tb",
        ),
    )
    version = service.create_rtl_version(
        frozen.spec_id, "module counter; endmodule", "direct_llm", source_ref="input:rtl-1"
    )
    service.record_verification(version.version_id, VerificationStatus.PASSED, "run-verify-1")
    evidence = EvidenceRef(
        evidence_id="evidence:gds-1", owner_id="user-1", spec_id=frozen.spec_id,
        candidate_id=version.version_id, run_id="run-gds-1",
        artifact_ids=("artifact:gds-1", "artifact:def-1"), evidence_kind="rtl_to_gds",
        status="succeeded", sha256="a" * 64, toolchain_digest="b" * 64,
        protocol_digest="c" * 64, claim_boundary="One verified Nangate45 run.",
        created_at="2026-09-19T00:00:00Z",
    )

    stored = service.record_evidence(evidence)

    assert stored.evidence_id == evidence.evidence_id
    assert service.get_evidence(evidence.evidence_id).complete is True


def test_gds_evidence_without_gds_artifact_is_rejected() -> None:
    service = M1Service.in_memory()
    session = service.assess_spec("user-1", spec=spec_ir())
    frozen = service.freeze_spec(session.spec_id)
    version = service.create_rtl_version(
        frozen.spec_id, "module counter; endmodule", "direct_llm", source_ref="input:rtl-1"
    )
    evidence = EvidenceRef(
        evidence_id="evidence:no-gds", owner_id="user-1", spec_id=frozen.spec_id,
        candidate_id=version.version_id, run_id="run-gds-1", artifact_ids=("artifact:def-1",),
        evidence_kind="rtl_to_gds", status="succeeded", sha256="a" * 64,
        toolchain_digest="b" * 64, protocol_digest="c" * 64,
        claim_boundary="No complete layout.", created_at="2026-09-19T00:00:00Z",
    )

    with pytest.raises(ValueError, match="artifact:gds"):
        service.record_evidence(evidence)


def test_m1_submits_a_typed_task_to_v2_and_returns_only_the_kernel_run_id() -> None:
    service = M1Service.in_memory()
    session = service.assess_spec("user-1", spec=spec_ir())
    frozen = service.freeze_spec(session.spec_id)
    service.register_verification_package(
        frozen.spec_id,
        VerificationPackage(
            verification_id="verify-counter-v1", spec_id=frozen.spec_id,
            compile_checks=("verilator-lint",),
            simulation_oracle_refs=("artifact:oracle-counter-v1",),
        ),
    )
    version = service.create_rtl_version(
        frozen.spec_id, "module counter; endmodule", "direct_llm", source_ref="input:rtl-1"
    )
    fake_v2 = _Submitter()

    task = service.submit_verification(version.version_id, fake_v2)

    assert task == "run-verify-1"
    assert fake_v2.submitted[0]["plugin_id"] == "rtl-verify"
    assert fake_v2.keys == ["m1-verify-" + version.version_id]


class _Submitter:
    def __init__(self) -> None:
        self._plugins = [{"plugin_id": "rtl-verify", "executable": True,
                          "admission": "admitted", "capabilities": ["eda.rtl.verify"]}]
        self.submitted: list[dict[str, object]] = []
        self.keys: list[str] = []

    def plugins(self) -> list[dict[str, object]]:
        return self._plugins

    def submit(self, task: dict[str, object], *, idempotency_key: str) -> dict[str, object]:
        self.submitted.append(task)
        self.keys.append(idempotency_key)
        return {"run": {"run_id": "run-verify-1", "status": "queued"}}


class _Plugins:
    def __init__(self, plugins: list[dict[str, object]]) -> None:
        self._plugins = plugins

    def plugins(self) -> list[dict[str, object]]:
        return self._plugins


def test_m1_state_survives_reopening_its_own_database(tmp_path: Path) -> None:
    database = tmp_path / "m1.sqlite"
    first_service = M1Service.open(str(database))
    session = first_service.assess_spec("user-1", spec=spec_ir())
    frozen = first_service.freeze_spec(session.spec_id)
    version = first_service.create_rtl_version(
        frozen.spec_id, "module counter; endmodule", "direct_llm", source_ref="input:rtl-1"
    )
    first_service.register_verification_package(
        frozen.spec_id,
        VerificationPackage(
            verification_id="verify-counter-v1",
            spec_id=frozen.spec_id,
            compile_checks=("verilator-lint",),
            simulation_oracle_refs=("artifact:oracle-counter-v1",),
        ),
    )
    first_service.store.close()

    second_service = M1Service.open(str(database))

    assert second_service.get_rtl_version(version.version_id).rtl_sha256 == version.rtl_sha256
    assert second_service.get_session(frozen.spec_id).state is M1State.FROZEN
    assert second_service.get_verification_package(frozen.spec_id).verification_id == "verify-counter-v1"
    second_service.store.close()
