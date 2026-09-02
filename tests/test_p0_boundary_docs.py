from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_p0_governance_documents_do_not_claim_uncommitted_l2_admission() -> None:
    text = (ROOT / "docs/governance/ARCHITECTURE_AUDIT.md").read_text(encoding="utf-8")
    inventory = (ROOT / "docs/governance/LEGACY_CLEANUP_INVENTORY.md").read_text(encoding="utf-8")
    boundary = (ROOT / "docs/governance/P0_PRODUCT_BOUNDARY_FREEZE.md").read_text(encoding="utf-8")
    api = subprocess.check_output(
        ["git", "show", "HEAD:apps/api/app.py"], cwd=ROOT, text=True,
    )
    assert "root `ARCHITECTURE.md`" not in text
    assert "Slice 003 has removed" not in text
    assert "integrations/orfs_agent/`" not in text
    assert "Future ORFS-Agent integration and adapter | UNKNOWN" in inventory
    assert "POST /api/v2/closed-loops" in boundary
    assert "external-optimizer-loops" not in boundary
    assert 'if path == "/api/v2/closed-loops":' in api
    assert "state.start_bayesian_closed_loop(" in api
    assert 'if path == "/api/designs/import":' in api
    for later_only in ("5,083", "optimizer_plugins.py", "state_tuning.py",
                       "industrial_dse_protocol.py", "optimization_memory.py",
                       "TaskFactory/PluginRegistry", "L1ORFSToolService",
                       "integrations/statetune/"):
        assert later_only not in text + inventory
