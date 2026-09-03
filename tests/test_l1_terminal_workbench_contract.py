"""The terminal Harness remains a projection over the durable L1 API."""
from pathlib import Path


def test_terminal_harness_exposes_guided_runtime_facts_not_local_state() -> None:
    source = (Path(__file__).parents[1] / "apps/l1_workbench/terminal_dashboard.py").read_text()
    for label in ("1 GOAL / IR", "2 TOOL / POLICY", "3 STATE / EVIDENCE",
                  "4 REFLECTION / REPLAY", "USER CLIENT — input & control",
                  ":advance", ":query <timing|congestion|drc|power|metrics>",
                  ":artifact <report|log|run_result|config>", ":stage <allowed-stage>"):
        assert label in source
    assert "/api/l1/sessions/" in source
    assert "hidden chain-of-thought" in source
    assert "subprocess" not in source
    assert "os.system" not in source
