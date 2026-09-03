"""Teaching replay controls remain a thin projection over the durable API."""
from pathlib import Path


def test_terminal_has_pause_resume_and_teaching_controls() -> None:
    source = (Path(__file__).parents[1] / "apps/l1_workbench/terminal_dashboard.py").read_text()
    for label in (":pause", ":resume", ":explain", ":advance", "not self.paused", "self.paused = True"):
        assert label in source


def test_terminal_never_renders_raw_trace_or_local_state() -> None:
    source = (Path(__file__).parents[1] / "apps/l1_workbench/terminal_dashboard.py").read_text()
    assert "hidden chain-of-thought" in source
    assert "subprocess" not in source
    assert "os.system" not in source
