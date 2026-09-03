#!/usr/bin/env python3
"""Run the managed L1 tutorial against the admitted local ORFS toolchain."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
for source in (ROOT / "packages/contracts/src", ROOT / "packages/scheduler/src", ROOT / "packages/execution/src", ROOT):
    sys.path.insert(0, str(source))

from apps.l1_workbench.service import WorkbenchService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--rtl", default=ROOT / "tests/fixtures/p2_mux_2to1.v", type=Path)
    parser.add_argument("--top", default="mux_2to1")
    parser.add_argument("--platform", default="nangate45")
    parser.add_argument("--clock-period-ns", default=10.0, type=float)
    args = parser.parse_args()
    output = args.output_root.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"acceptance output must be empty: {output}")
    service = WorkbenchService(output, backend="orfs", rtl=args.rtl,
                               top=args.top, platform_name=args.platform,
                               clock_period_ns=args.clock_period_ns)
    session = service.start(
        "Improve setup timing; area no more than +3%; protect RTL and SDC; use at most three runs."
    )
    for answer in (
        ("objective", "objective", "timing"),
        ("constraints", "constraints", "drc_zero_area_plus_3pct"),
        ("clock_sdc", "clock_sdc_policy", "protect_clock_sdc"),
        ("change_scope", "change_scope", "registered_parameters_only"),
        ("budget", "budget", "3"),
    ):
        session = service.answer(session.session_id, [{
            "question_id": answer[0], "field": answer[1], "value": answer[2],
        }])
    actions = []
    for _ in range(8):
        result = service.advance(session.session_id)
        actions.append(result["decision"]["action"])
        if result["decision"]["action"] == "stop":
            break
    state, _ = service._load(session.session_id)
    events = service.events(session.session_id)
    expected = ["run_full_flow", "query_timing", "reflect_continue", "run_route", "query_drc", "stop"]
    if actions != expected:
        raise RuntimeError(f"unexpected tutorial action sequence: {actions!r}")
    if state.remaining_budget.max_eda_runs != 1:
        raise RuntimeError("observed Runtime runs did not consume the expected budget")
    if not any(event["kind"] == "reflection_recorded" and event["facts"].get("decision") == "stop" for event in events):
        raise RuntimeError("tutorial has no durable terminal reflection")
    summary = {
        "schema_version": 1,
        "accepted": True,
        "session_id": session.session_id,
        "goal_id": session.goal_id,
        "actions": actions,
        "final_state": state.to_dict(),
        "event_kinds": [event["kind"] for event in events],
        "terminal_reflection": next(event for event in reversed(events)
                                    if event["kind"] == "reflection_recorded")["facts"],
    }
    (output / "l1_tutorial_acceptance_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
