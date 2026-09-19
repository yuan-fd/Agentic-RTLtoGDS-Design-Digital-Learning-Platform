from __future__ import annotations

import sys
from pathlib import Path

import pytest

M1_SRC = Path(__file__).parents[1] / "apps/m1_rtl_to_gds/src"
if str(M1_SRC) not in sys.path:
    sys.path.insert(0, str(M1_SRC))

from openroad_app_m1.generator import DirectLLMGenerator  # noqa: E402
from openroad_app_m1.models import M1State  # noqa: E402
from openroad_app_m1.service import M1Service  # noqa: E402
from openroad_platform_contracts.rtl_frontend import PortSpec, SpecIR  # noqa: E402


def spec() -> SpecIR:
    return SpecIR(
        spec_id="spec-fsm", design_id="course-fsm", top="fsm",
        functionality="single-clock sequence detector", objective="teach FSM RTL",
        ports=(PortSpec("clk", "input", 1), PortSpec("din", "input", 1),
               PortSpec("hit", "output", 1)),
        clock="clk", constraints={"clock_period_ns": 5.0},
        acceptance_criteria=("hit follows the frozen sequence table",),
    )


class Provider:
    def __init__(self, output: object) -> None:
        self.output = output
        self.calls: list[dict] = []

    def generate(self, payload: dict) -> object:
        self.calls.append(payload)
        if isinstance(self.output, BaseException):
            raise self.output
        return self.output


class UploadClient:
    def upload_rtl(self, rtl: str) -> dict[str, str]:
        return {"input_id": "input-generated-1"}


def test_direct_llm_requires_a_frozen_spec_and_stages_new_rtl() -> None:
    service = M1Service.in_memory()
    session = service.assess_spec("user-1", spec=spec())
    provider = Provider("module fsm(input logic clk, din, output logic hit); endmodule")

    with pytest.raises(ValueError, match="frozen"):
        DirectLLMGenerator(service).generate(session.spec_id, provider, UploadClient())

    frozen = service.freeze_spec(session.spec_id)
    version = DirectLLMGenerator(service).generate(frozen.spec_id, provider, UploadClient())

    assert version.generator == "direct_llm"
    assert version.source_ref == "input:input-generated-1"
    assert provider.calls[0]["spec_id"] == frozen.spec_id
    assert service.get_session(frozen.spec_id).state is M1State.FROZEN


def test_provider_failure_does_not_create_a_candidate_or_use_old_rtl() -> None:
    service = M1Service.in_memory()
    session = service.assess_spec("user-1", spec=spec())
    frozen = service.freeze_spec(session.spec_id)
    provider = Provider(RuntimeError("model capacity unavailable"))

    with pytest.raises(RuntimeError, match="capacity"):
        DirectLLMGenerator(service).generate(frozen.spec_id, provider, UploadClient())

    assert not service.list_rtl_versions(frozen.spec_id)


def test_provider_output_is_staged_as_a_new_rtl_version() -> None:
    service = M1Service.in_memory()
    session = service.assess_spec("user-1", spec=spec())
    frozen = service.freeze_spec(session.spec_id)

    version = DirectLLMGenerator(service).generate(
        frozen.spec_id, Provider("module fsm; endmodule"), UploadClient()
    )
    assert version.generator == "direct_llm"
