from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "integrations/orfs_agent/orfs_agent_paper_policy_adapter.py"
spec = importlib.util.spec_from_file_location("orfs_agent_paper_policy_adapter", PATH)
assert spec and spec.loader
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


def _candidate() -> dict[str, float | int]:
    return {"CLK": 4.5, "UTIL": 20, "TNS_End_Percent": 100, "GP_PAD": 0,
            "DP_PAD": 0, "DPO": 1, "PIN_ADJ": .4, "UP_ADJ": .4,
            "LB_ADDON": .4936, "HIER_SYNTH": 0, "CTS_CSIZE": 10, "CTS_CDIA": 80}


def test_paper_row_retains_full_candidate_and_computes_ecp() -> None:
    row = adapter._row({"candidate": _candidate(), "metrics": {"finish__timing__setup__ws": -.2}},
                       design="aes", platform="sky130hd", target="ECP_final")
    assert set(adapter.PARAMETERS).issubset(row)
    assert row["ECP_final"] == 4.7


def test_combo_uses_upstream_paper_baseline_definition() -> None:
    row = adapter._row({"candidate": _candidate(), "metrics": {
        "finish__timing__setup__ws": -.2, "detailedroute__route__wirelength": 589825.0}},
                       design="aes", platform="sky130hd", target="Fractional_Loss_final")
    assert row["Fractional_Loss_final"] > 1.0


def test_paper_policy_has_no_dependency_on_the_legacy_eight_dimension_bridge() -> None:
    source = PATH.read_text(encoding="utf-8")
    assert 'orfs_agent_adapter.py' not in source
    assert 'orfs_agent_managed_analyst_policy.py' in source
