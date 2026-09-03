#!/usr/bin/env python3
"""L1→L2 gate acceptance: real ORFS M1 evidence then a typed escalation.

This proves the L1→L2 handoff boundary end to end at the authorization
stage: two distinct measured Runtime ORFS observations (baseline + candidate)
followed by a durable ``escalate`` reflection produce one typed
``L2HandoffAuthorization`` and a frozen ``OptimizationRequest`` bound to the
L1 trace/goal/state and the admitted ORFS-Agent source lock.

It intentionally does not submit ORFS-Agent search work: execution belongs to
the durable external campaign controller (the direct-submission path was
retired).  No optimizer runs and no PPA/QoR improvement is claimed here.
"""
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
for source in (ROOT / "packages/contracts/src", ROOT / "packages/scheduler/src",
               ROOT / "packages/execution/src", ROOT):
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
    parser.add_argument("--orfs-agent-source",
                        default=ROOT / ".external-src/orfs-agent-admission-20260830-vNWf4x/ORFS-Agent",
                        type=Path)
    args = parser.parse_args()
    output = args.output_root.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"acceptance output must be empty: {output}")
    source = args.orfs_agent_source.expanduser().resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"admitted ORFS-Agent checkout missing: {source}")
    lock = ROOT / "integrations/orfs_agent/source.lock.json"
    if not lock.is_file():
        raise FileNotFoundError("integrations/orfs_agent/source.lock.json is missing")
    port = _port()
    env = {**os.environ, "PYTHONPATH": ":".join(str(ROOT / item) for item in
           ("packages/contracts/src", "packages/scheduler/src", "packages/execution/src", "."))}
    server = subprocess.Popen([sys.executable, "apps/l1_workbench/server.py",
        "--state-root", str(output), "--port", str(port), "--backend", "orfs",
        "--rtl", str(args.rtl), "--top", args.top, "--platform", args.platform,
        "--clock-period-ns", str(args.clock_period_ns),
        "--orfs-agent-source", str(source)], cwd=ROOT, env=env)
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
        session = _post(base, f"/api/l1/sessions/{session['session_id']}/answers", {"answers": [{
            "question_id": "change_scope", "field": "change_scope", "value": "registered_parameters_only",
        }, {
            "question_id": "design_context", "field": "design_context", "value": "managed_mux_default_corner_baseline",
        }]})
        if not session["goal_id"]:
            raise RuntimeError("semantic clarification did not produce a frozen Goal IR")
        sid = session["session_id"]
        baseline = _post(base, f"/api/l1/sessions/{sid}/execute",
                         {"decision_summary": "Run the frozen baseline before selecting any registered parameter change."})
        baseline_run_id = baseline["plan"]["run_id"]
        proposal = _post(base, f"/api/l1/sessions/{sid}/m1-proposal", {})
        candidate = _post(base, f"/api/l1/sessions/{sid}/candidates", {
            "proposal_id": proposal["proposal_id"],
            "decision_summary": proposal.get("proposal", {}).get("summary", "Execute the approved M1 candidate proposal.")})
        candidate_run_id = candidate["plan"]["run_id"]
        comparison = _post(base, f"/api/l1/sessions/{sid}/m1-compare", {"baseline_run_id": baseline_run_id})
        if baseline["state"]["diagnosis"].get("runtime_terminal_status") != "succeeded":
            raise RuntimeError("gate acceptance requires a successful Runtime baseline attempt")
        if candidate["state"]["diagnosis"].get("runtime_terminal_status") != "succeeded":
            raise RuntimeError("gate acceptance requires a successful Runtime candidate attempt")
        state = candidate["state"]
        events = json.loads(urlopen(base + f"/api/l1/sessions/{sid}/events", timeout=10).read())["events"]
        if state["remaining_budget"]["max_eda_runs"] != 1:
            raise RuntimeError("baseline and candidate did not consume exactly two frozen EDA-run budget units")
        escalation = _post(base, f"/api/l1/sessions/{sid}/l2-escalate", {})
        authorization = escalation["authorization"]
        request = escalation["request"]
        if not authorization or not request:
            raise RuntimeError("L2 escalation returned no authorization/request")
        if authorization["l1_trace_id"] != request["l1_trace_id"]:
            raise RuntimeError("L2 authorization does not bind the L1 trace")
        if authorization["source_state_id"] != request["source_state_id"]:
            raise RuntimeError("L2 authorization does not bind the terminal L1 state")
        if request["source_state_id"] != state["state_id"]:
            raise RuntimeError("frozen OptimizationRequest does not bind the observed candidate state")
        if (request["plugin_id"], request["capability"]) != ("orfs-agent", "optimizer.l2.propose"):
            raise RuntimeError("frozen OptimizationRequest is not the admitted L2 capability")
        fresh_events = json.loads(urlopen(base + f"/api/l1/sessions/{sid}/events", timeout=10).read())["events"]
        kinds = [event["kind"] for event in fresh_events]
        if "l2_handoff_authorized" not in kinds:
            raise RuntimeError("no durable L2_HANDOFF_AUTHORIZED trace event was recorded")
        if "reflection_recorded" not in kinds:
            raise RuntimeError("no durable escalate reflection was recorded")
        terminal_reflection = next(event for event in reversed(fresh_events)
                                   if event["kind"] == "reflection_recorded")
        summary = {
            "schema_version": 1,
            "accepted": True,
            "session_id": sid,
            "goal_id": session["goal_id"],
            "baseline_run_id": baseline_run_id,
            "candidate_run_id": candidate_run_id,
            "m1_decision": comparison["decision"],
            "authorization": authorization,
            "optimization_request": request,
            "event_kinds": kinds,
            "terminal_reflection": terminal_reflection["facts"],
            "claim_boundary": ("L2 authorization gate passed with real ORFS evidence; "
                               "no ORFS-Agent search execution was submitted"),
        }
        (output / "l1_l2_gate_acceptance_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(summary, sort_keys=True))
        return 0
    finally:
        server.terminate(); server.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
