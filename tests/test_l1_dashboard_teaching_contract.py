"""Regression checks for the read-only Hands-on teaching projection."""
from pathlib import Path


def test_dashboard_keeps_tutorial_facts_and_never_renders_raw_trace_payloads() -> None:
    source = (Path(__file__).parents[1] / "apps/l1_trace_dashboard/app.js").read_text()
    for label in ("User request", "Clarification", "Final typed Goal IR",
                  "Typed Tool", "Policy provenance", "Runtime Receipt",
                  "Verified DesignState", "Recorded hypotheses (unverified)",
                  "Planner-visible summary, not hidden reasoning",
                  "Planner-visible tool choice (not hidden reasoning)"):
        assert label in source
    assert "Raw durable audit fields" not in source
    assert "JSON.stringify(x,null,2)" not in source
    assert "innerHTML = audit(events)" in source


def test_dashboard_is_four_panels_on_wide_screens_and_handles_partial_history() -> None:
    root = Path(__file__).parents[1]
    source = (root / "apps/l1_trace_dashboard/app.js").read_text()
    style = (root / "apps/l1_trace_dashboard/style.css").read_text()
    assert "filter(x => x && typeof x.ref === \"string\" && x.ref)" in source
    assert "Historical trace: tool-choice summary not stored." in source
    assert "grid-template-columns:repeat(4,minmax(0,1fr))" in style
    assert "@media(max-width:1200px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}" in style
