"""Thin HTTP API for the real L1 vertical slice."""
import argparse,json
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse,parse_qs
try:
 from .service import WorkbenchService
except ImportError:
 from service import WorkbenchService
def main():
 p=argparse.ArgumentParser();p.add_argument("--state-root",type=Path,required=True);p.add_argument("--port",type=int,default=8766)
 p.add_argument("--backend",choices=("smoke","orfs"),default="smoke",help="smoke is test-only; orfs executes the admitted local EDA toolchain")
 p.add_argument("--rtl",type=Path);p.add_argument("--top",default="mux_2to1");p.add_argument("--platform",default="nangate45");p.add_argument("--clock-period-ns",type=float,default=10.0);p.add_argument("--orfs-agent-source",type=Path)
 a=p.parse_args();svc=WorkbenchService(a.state_root,backend=a.backend,rtl=a.rtl,top=a.top,platform_name=a.platform,clock_period_ns=a.clock_period_ns,orfs_agent_source=a.orfs_agent_source)
 class H(BaseHTTPRequestHandler):
  def reply(self,x,code=200):
   b=json.dumps(x).encode();self.send_response(code);self.send_header("Content-Type","application/json");self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b)
  def do_POST(self):
   try:
    x=json.loads(self.rfile.read(int(self.headers.get("Content-Length",0)))); parts=self.path.strip("/").split("/")
    if self.path=="/api/l1/sessions": s=svc.start(x["text"]); return self.reply(s.to_dict())
    sid=parts[3]
    if parts[-1]=="answers": return self.reply(svc.answer(sid,x["answers"]).to_dict())
    if parts[-1]=="execute": p,state=svc.execute(sid,x["decision_summary"],wait=x.get("wait",True));return self.reply({"plan":p,"state":state.to_dict(),"runtime":svc.runtime.describe(p["run_id"])})
    if parts[-1]=="parameters": return self.reply(svc.set_flow_params(sid,x["values"],x["decision_summary"]))
    if parts[-1]=="m1-proposal": return self.reply(svc.propose_m1_candidate(sid))
    if parts[-1]=="candidates": p,state=svc.run_candidate(sid,x["proposal_id"],x["decision_summary"],wait=x.get("wait",True));return self.reply({"plan":p,"state":state.to_dict(),"runtime":svc.runtime.describe(p["run_id"])})
    if parts[-1]=="m1-compare": return self.reply(svc.compare_m1_candidate(sid,x["baseline_run_id"],x.get("decision_summary")))
    if parts[-1]=="l2-upgrade": return self.reply(svc.l2_upgrade(sid,wait=x.get("wait",False)))
    if parts[-1]=="queries": return self.reply(svc.query(sid,x["kind"],x["decision_summary"],limit=x.get("limit",20)))
    if parts[-1]=="artifacts": return self.reply(svc.artifact_excerpt(sid,x["kind"],x["decision_summary"],max_bytes=x.get("max_bytes",4096)))
    if parts[-1]=="stages": p,state=svc.run_stage(sid,x["stage"],x["decision_summary"],wait=x.get("wait",True));return self.reply({"plan":p,"state":state.to_dict(),"runtime":svc.runtime.describe(p["run_id"])})
    if parts[-1]=="advance": return self.reply(svc.advance(sid))
    if parts[-1]=="cancel":return self.reply(svc.cancel(sid,x["reason"]))
    if parts[-1]=="recover":return self.reply(svc.recover(sid).to_dict())
    self.reply({"error":"not found"},404)
   except Exception as e:self.reply({"error":str(e)},400)
  def do_GET(self):
   try:
    parts=self.path.split("?")[0].strip("/").split("/");q=parse_qs(urlparse(self.path).query);self.reply({"events":svc.events(parts[3],int(q.get("after",[-1])[0]))})
   except Exception as e:self.reply({"error":str(e)},400)
 ThreadingHTTPServer(("127.0.0.1",a.port),H).serve_forever()
if __name__=="__main__":main()
