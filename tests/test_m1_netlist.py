from __future__ import annotations

import sys
from pathlib import Path

M1_SRC = Path(__file__).parents[1] / "apps/m1_rtl_to_gds/src"
if str(M1_SRC) not in sys.path:
    sys.path.insert(0, str(M1_SRC))

from openroad_app_m1.netlist import render_netlist_svg  # noqa: E402


def test_netlist_renderer_is_deterministic_and_uses_source_names():
    source = "module top;\n  AND2_X1 u0 (.A(a), .B(b), .Y(y));\nendmodule\n"

    first = render_netlist_svg(source)
    second = render_netlist_svg(source)

    assert first == second
    assert "AND2_X1" in first
    assert "u0" in first


def test_netlist_renderer_returns_unavailable_for_non_netlist_text():
    assert render_netlist_svg("not a netlist") is None
