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
        "帮我改善 mux 的 setup timing，但面积不能比 baseline 增加超过 3%，"
        "不许修改 RTL/SDC，最多跑 3 次。"
    )
    # The semantic draft attributes explicit user facts and asks only policy
    # omissions: protected change scope and the managed corner/baseline.
    session = service.answer(session.session_id, [{
        "question_id": "change_scope", "field": "change_scope", "value": "registered_parameters_only",
    }, {
        "question_id": "design_context", "field": "design_context", "value": "managed_mux_default_corner_baseline",
    }])
    if not session.goal_id:
        raise RuntimeError("semantic clarification did not produce a frozen Goal IR")
    baseline_plan, baseline_state = service.execute(
        session.session_id,
        "Run the frozen baseline before selecting any registered parameter change.",
    )
    baseline_run_id = baseline_plan["run_id"]
    proposal = service.propose_m1_candidate(session.session_id)
    candidate_plan, candidate_state = service.run_candidate(
        session.session_id, proposal["proposal_id"], proposal["proposal"]["summary"],
    )
    candidate_run_id = candidate_plan["run_id"]
    comparison = service.compare_m1_candidate(session.session_id, baseline_run_id)
    actions = ["run_full_flow_baseline", "set_flow_params", "run_full_flow_candidate",
               "compare_runs", comparison["decision"]]
    state, _ = service._load(session.session_id)
    events = service.events(session.session_id)
    if state.remaining_budget.max_eda_runs != 1:
        raise RuntimeError("baseline and candidate did not consume exactly two frozen EDA-run budget units")
    if baseline_state.diagnosis.get("runtime_terminal_status") != "succeeded" or candidate_state.diagnosis.get("runtime_terminal_status") != "succeeded":
        raise RuntimeError("M1 acceptance requires successful Runtime baseline and candidate attempts")
    if service.runtime.describe(baseline_run_id)["run"]["status"] != "succeeded" or service.runtime.describe(candidate_run_id)["run"]["status"] != "succeeded":
        raise RuntimeError("M1 acceptance requires successful Runtime run records")
    candidate_task = service.runtime.describe(candidate_run_id)["run"]["task_spec"]
    if candidate_task["parameters"].get("place_density") != 0.5:
        raise RuntimeError("candidate Runtime TaskSpec did not receive the approved parameter patch")
    if not any(event["kind"] == "reflection_recorded" and event["facts"].get("decision") == comparison["decision"] for event in events):
        raise RuntimeError("M1 comparison has no durable evidence-backed final reflection")
    summary = {
        "schema_version": 1,
        "accepted": True,
        "session_id": session.session_id,
        "goal_id": session.goal_id,
        "actions": actions,
        "baseline_run_id": baseline_run_id,
        "candidate_run_id": candidate_run_id,
        "baseline_state": baseline_state.to_dict(),
        "candidate_state": candidate_state.to_dict(),
        "candidate_task_parameters": candidate_task["parameters"],
        "m1_proposal": proposal["proposal"],
        "comparison": comparison,
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
