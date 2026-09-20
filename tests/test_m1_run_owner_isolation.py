import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "apps/m1_rtl_to_gds/src"))

from openroad_app_m1.service import M1Service
from openroad_app_m1.models import VerificationStatus
from openroad_platform_contracts.rtl_frontend import PortSpec, SpecIR


def _spec() -> SpecIR:
    return SpecIR(
        spec_id="spec-owner", design_id="course-counter", top="counter",
        functionality="bounded counter", objective="owner test",
        ports=(PortSpec("clk", "input", 1), PortSpec("q", "output", 1)),
        clock="clk", constraints={"clock_period_ns": 5.0},
        acceptance_criteria=("q changes",),
    )


def test_m1_run_owner_lookup_rejects_another_identity():
    service = M1Service.in_memory()
    session = service.assess_spec("owner-a", spec=_spec())
    frozen = service.freeze_spec(session.spec_id)
    version = service.create_rtl_version(frozen.spec_id, "module counter; endmodule", "test")
    service.record_verification(version.version_id, VerificationStatus.PASSED, "run-owner")
    try:
        service.assert_run_owner("run-owner", "owner-b")
    except PermissionError as exc:
        assert "another" in str(exc)
    else:
        raise AssertionError("another identity accessed the run")
    try:
        service.assert_run_owner("run-unknown", "owner-a")
    except KeyError as exc:
        assert "run-unknown" in str(exc)
    else:
        raise AssertionError("unknown run was accepted")
