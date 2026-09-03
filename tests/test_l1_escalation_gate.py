"""The L1→L2 escalation gate is visible, typed, and never auto-submits."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "apps" / "l1_workbench"))

from service import WorkbenchService  # noqa: E402


def test_escalation_gate_requires_the_real_orfs_backend(tmp_path):
    service = WorkbenchService(tmp_path, backend="smoke")
    with pytest.raises(ValueError, match="orfs"):
        service.l2_escalate("l1-session-unused")


def test_terminal_exposes_the_l2_authorization_command():
    source = (Path(__file__).parents[1] / "apps/l1_workbench/terminal_dashboard.py").read_text()
    assert ":l2" in source
    assert "/l2-escalate" in source


def test_service_route_is_exposed_by_the_thin_http_server():
    source = (Path(__file__).parents[1] / "apps/l1_workbench/server.py").read_text()
    assert 'l2-escalate' in source
