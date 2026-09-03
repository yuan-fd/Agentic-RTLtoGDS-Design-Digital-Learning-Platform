import json, os, socket, subprocess, sys, time
from pathlib import Path
from urllib.request import Request, urlopen
import pytest

ROOT = Path(__file__).parents[1]
ENV = {**os.environ, "PYTHONPATH": ":".join(str(ROOT / path) for path in ("packages/contracts/src", "packages/scheduler/src", "packages/execution/src", "."))}

def _free_port():
 s=socket.socket();s.bind(("127.0.0.1",0));port=s.getsockname()[1];s.close();return port
def _post(url, payload):
 data=json.dumps(payload).encode();return json.loads(urlopen(Request(url,data=data,headers={"Content-Type":"application/json"}),timeout=10).read())

def test_real_l1_workbench_api_vertical_slice(tmp_path):
 port=_free_port(); proc=subprocess.Popen([sys.executable,"apps/l1_workbench/server.py","--state-root",str(tmp_path),"--port",str(port)],cwd=ROOT,env=ENV)
 base=f"http://127.0.0.1:{port}"
 try:
  for _ in range(100):
   try: urlopen(base+"/api/l1/sessions/none/events",timeout=.1);break
   except Exception: time.sleep(.03)
  started=_post(base+"/api/l1/sessions",{"text":"Run one bounded implementation flow."})
  assert started["status"]=="clarification_required"
  sid=started["session_id"]
  frozen=_post(base+f"/api/l1/sessions/{sid}/answers",{"answers":[{"question_id":"objective-1","field":"objective","value":"one audited run"}]})
  assert frozen["status"]=="goal_finalized" and frozen["goal_id"]
  result=_post(base+f"/api/l1/sessions/{sid}/execute",{"decision_summary":"Execute one bounded typed Runtime tool."})
  assert result["runtime"]["run"]["status"]=="succeeded"
  artifact=result["runtime"]["stages"][0]["attempts"][0]["artifacts"][0]
  assert artifact["kind"]=="report" and artifact["sha256"]
  assert result["runtime"]["stages"][0]["attempts"][0]["exit_code"] == 0
  assert (tmp_path / "work" / result["plan"]["run_id"]).exists()
  query=_post(base+f"/api/l1/sessions/{sid}/queries",{"kind":"timing","limit":20,"decision_summary":"Read timing facts from the Runtime-owned baseline."})
  assert query["receipt"]["status"] == "completed"
  assert query["receipt"]["result"]["runs"][0]["run_id"] == result["plan"]["run_id"]
  proposal=_post(base+f"/api/l1/sessions/{sid}/parameters",{"values":{"place_density":.5},"decision_summary":"Transport test only; no QoR claim."})
  candidate=_post(base+f"/api/l1/sessions/{sid}/candidates",{"proposal_id":proposal["proposal_id"],"decision_summary":"Consume the approved transport-only proposal."})
  assert candidate["runtime"]["run"]["status"]=="succeeded"
  assert candidate["runtime"]["run"]["task_spec"]["parameters"]["place_density"] == .5
  import urllib.error
  with pytest.raises(urllib.error.HTTPError) as duplicate:
   _post(base+f"/api/l1/sessions/{sid}/candidates",{"proposal_id":proposal["proposal_id"],"decision_summary":"must reject duplicate"})
  assert duplicate.value.code == 400
  excerpt=_post(base+f"/api/l1/sessions/{sid}/artifacts",{"kind":"report","max_bytes":128,"decision_summary":"Read the registered bounded report excerpt."})
  assert excerpt["receipt"]["status"] == "completed"
  assert excerpt["receipt"]["result"]["artifact_id"]
  events=json.loads(urlopen(base+f"/api/l1/sessions/{sid}/events?after=1",timeout=10).read())["events"]
  kinds=[event["kind"] for event in events]
  assert "goal_finalized" in kinds and "tool_called" in kinds and "policy_decided" in kinds and "tool_receipt" in kinds and "state_transition" in kinds
  assert kinds.count("tool_receipt") >= 3
  assert all(event.get("planner_summary") != "hidden reasoning" for event in events)
  assert _post(base+f"/api/l1/sessions/{sid}/recover",{})["status"]=="goal_finalized"
  # A second real session keeps its Runtime subprocess active long enough for
  # the API cancellation route to reach Runtime's controlled cancel port.
  second=_post(base+"/api/l1/sessions",{"text":"Run a cancellable bounded flow."}); sid2=second["session_id"]
  _post(base+f"/api/l1/sessions/{sid2}/answers",{"answers":[{"question_id":"objective-1","field":"objective","value":"cancel the bounded run"}]})
  pending=_post(base+f"/api/l1/sessions/{sid2}/execute",{"decision_summary":"Start bounded run for cancellation.","wait":False})
  assert _post(base+f"/api/l1/sessions/{sid2}/cancel",{"reason":"operator cancellation smoke"})["status"]=="cancel_requested"
  for _ in range(100):
   view=json.loads(urlopen(base+f"/api/l1/sessions/{sid2}/events",timeout=10).read())["events"]
   if any(event["kind"]=="state_transition" for event in view): break
   time.sleep(.05)
  cancelled=[event for event in view if event["kind"]=="state_transition"]
  assert cancelled and cancelled[-1]["facts"]["terminal_status"] == "cancelled"
 finally:
  proc.terminate();proc.wait(timeout=5)
