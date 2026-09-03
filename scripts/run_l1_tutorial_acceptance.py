#!/usr/bin/env python3
"""Run the managed L1 tutorial against the admitted local ORFS toolchain."""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError


ROOT = Path(__file__).resolve().parents[1]
for source in (ROOT / "packages/contracts/src", ROOT / "packages/scheduler/src", ROOT / "packages/execution/src", ROOT):
    sys.path.insert(0, str(source))

def _port() -> int:
    sock = socket.socket(); sock.bind(("127.0.0.1", 0))
    value = sock.getsockname()[1]; sock.close()
    return value


def _post(base: str, path: str, payload: dict) -> dict:
    request = Request(base + path, data=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json"})
    return json.loads(urlopen(request, timeout=7300).read())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--rtl", default=ROOT / "tests/fixtures/p2_mux_2to1.v", type=Path)
    parser.add_argument("--top", default="mux_2to1")
    parser.add_argument("--platform", default="nangate45")
    parser.add_argument("--clock-period-ns", default=10.0, type=float)
    parser.add_argument("--failure-candidate", action="store_true",
                        help="exercise the real Runtime failed-candidate exit; never a QoR claim")
    args = parser.parse_args()
    output = args.output_root.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"acceptance output must be empty: {output}")
    port = _port()
    env = {**os.environ, "PYTHONPATH": ":".join(str(ROOT / source) for source in
           ("packages/contracts/src", "packages/scheduler/src", "packages/execution/src", "."))}
    server = subprocess.Popen([sys.executable, "apps/l1_workbench/server.py",
        "--state-root", str(output), "--port", str(port), "--backend", "orfs",
        "--rtl", str(args.rtl), "--top", args.top, "--platform", args.platform,
        "--clock-period-ns", str(args.clock_period_ns)], cwd=ROOT, env=env)
    base = f"http://127.0.0.1:{port}"
    try:
      for _ in range(100):
        try:
            urlopen(base + "/api/l1/sessions/none/events", timeout=.2)
            break
        except HTTPError:
            break
        except Exception:
            time.sleep(.05)
      else:
        raise RuntimeError("L1 HTTP server did not start")
      session = _post(base, "/api/l1/sessions", {"text":
        "帮我改善 mux 的 setup timing，但面积不能比 baseline 增加超过 3%，"
        "不许修改 RTL/SDC，最多跑 3 次。"})
    # The semantic draft attributes explicit user facts and asks only policy
    # omissions: protected change scope and the managed corner/baseline.
      session = _post(base, f"/api/l1/sessions/{session['session_id']}/answers", {"answers": [{
        "question_id": "change_scope", "field": "change_scope", "value": "registered_parameters_only",
    }, {
        "question_id": "design_context", "field": "design_context", "value": "managed_mux_default_corner_baseline",
    }]})
      if not session["goal_id"]:
        raise RuntimeError("semantic clarification did not produce a frozen Goal IR")
      sid = session["session_id"]
      baseline = _post(base, f"/api/l1/sessions/{sid}/execute", {"decision_summary":"Run the frozen baseline before selecting any registered parameter change."})
      baseline_run_id = baseline["plan"]["run_id"]
      proposal = (_post(base, f"/api/l1/sessions/{sid}/parameters",
                  {"values":{"minimum_die_size_um":1.0},
                   "decision_summary":"Failure-exit acceptance: submit a bounded invalid floorplan size."})
                  if args.failure_candidate else
                  _post(base, f"/api/l1/sessions/{sid}/m1-proposal", {}))
      candidate = _post(base, f"/api/l1/sessions/{sid}/candidates", {
          "proposal_id":proposal["proposal_id"],
          "decision_summary":(proposal.get("proposal", {}).get("summary")
                              or "Execute the approved failure-exit parameter proposal.")})
      candidate_run_id = candidate["plan"]["run_id"]
      comparison = _post(base, f"/api/l1/sessions/{sid}/m1-compare", {"baseline_run_id":baseline_run_id})
      actions = ["run_full_flow_baseline", "set_flow_params", "run_full_flow_candidate",
                 "compare_runs", comparison["decision"]]
      state = candidate["state"]
      events = json.loads(urlopen(base+f"/api/l1/sessions/{sid}/events",timeout=10).read())["events"]
      if state["remaining_budget"]["max_eda_runs"] != 1:
        raise RuntimeError("baseline and candidate did not consume exactly two frozen EDA-run budget units")
      if baseline["state"]["diagnosis"].get("runtime_terminal_status") != "succeeded":
        raise RuntimeError("M1 acceptance requires successful Runtime baseline and candidate attempts")
      if not args.failure_candidate and state["diagnosis"].get("runtime_terminal_status") != "succeeded":
        raise RuntimeError("M1 success acceptance requires successful candidate attempt")
      if baseline["runtime"]["run"]["status"] != "succeeded":
        raise RuntimeError("M1 acceptance requires successful Runtime baseline record")
      candidate_task = candidate["runtime"]["run"]["task_spec"]
      if not args.failure_candidate and candidate_task["parameters"].get("place_density") != 0.5:
        raise RuntimeError("candidate Runtime TaskSpec did not receive the approved parameter patch")
      if args.failure_candidate and (comparison["decision"] != "stop" or comparison["area_baseline_ratio"] is not None
          or comparison["decision_reason"] != "candidate_not_observable"):
        raise RuntimeError("failed candidate was not returned as an auditable stop/unknown comparison")
      if not any(event["kind"] == "reflection_recorded" and event["facts"].get("decision") == comparison["decision"] for event in events):
        raise RuntimeError("M1 comparison has no durable evidence-backed final reflection")
      summary = {
        "schema_version": 1,
        "accepted": True,
        "session_id": session["session_id"],
        "goal_id": session["goal_id"],
        "actions": actions,
        "baseline_run_id": baseline_run_id,
        "candidate_run_id": candidate_run_id,
        "baseline_state": baseline["state"],
        "candidate_state": state,
        "candidate_task_parameters": candidate_task["parameters"],
        "m1_proposal": proposal["proposal"],
        "comparison": comparison,
        "final_state": state,
        "event_kinds": [event["kind"] for event in events],
        "terminal_reflection": next(event for event in reversed(events)
                                    if event["kind"] == "reflection_recorded")["facts"],
      }
      (output / "l1_tutorial_acceptance_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
      )
      print(json.dumps(summary, sort_keys=True))
      return 0
    finally:
      server.terminate(); server.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
