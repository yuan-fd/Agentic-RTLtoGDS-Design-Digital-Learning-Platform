"""Offline M1 contract smoke; no v2 or EDA process is claimed here."""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from openroad_app_m1.service import M1Service  # noqa: E402
from openroad_platform_contracts.rtl_frontend import PortSpec, SpecIR  # noqa: E402


def main() -> int:
    spec = SpecIR(
        spec_id="smoke-spec", design_id="smoke-counter", top="counter",
        functionality="bounded counter", objective="teaching smoke",
        ports=(PortSpec("clk", "input", 1), PortSpec("q", "output", 4)),
        clock="clk", constraints={"clock_period_ns": 10.0},
        acceptance_criteria=("q changes on a rising edge",),
    )
    service = M1Service.in_memory()
    session = service.assess_spec("smoke-user", spec=spec)
    frozen = service.freeze_spec(session.spec_id)
    version = service.create_rtl_version(frozen.spec_id, "module counter; endmodule", "smoke")
    request_failed = False
    try:
        service.build_rtl_to_gds_request(version.version_id, "nangate45")
    except ValueError:
        request_failed = True
    assert request_failed
    service.store.close()
    print("m1_rtl_to_gds smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
