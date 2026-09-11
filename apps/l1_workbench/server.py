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
 p.add_argument("--rtl",type=Path);p.add_argument("--top",default="mux_2to1");p.add_argument("--design-id");p.add_argument("--platform",default="nangate45");p.add_argument("--clock-period-ns",type=float,default=10.0);p.add_argument("--orfs-agent-source",type=Path)
 p.add_argument("--orfs-agent-paper-orfs",type=Path);p.add_argument("--orfs-agent-openroad-bin",type=Path);p.add_argument("--orfs-agent-yosys-bin",type=Path);p.add_argument("--orfs-agent-paper-environment",type=Path,help="operator-owned JSON map for audited paper toolchain libraries")
 p.add_argument("--a2-orfo-source",type=Path);p.add_argument("--a2-orfo-model",type=Path);p.add_argument("--a2-orfo-python",type=Path);p.add_argument("--a2-orfo-codex",type=Path)
 p.add_argument("--goal-provider",choices=("tutorial","codex"),default="tutorial",help="tutorial=deterministic mux parser; codex=managed Codex CLI structured provider")
 p.add_argument("--managed-reference",choices=("orfs-agent-paper-aes-sky130hd",),help="operator-owned full RTL/SDC reference; mutually exclusive with --rtl")
 p.add_argument("--l2-max-parallel",type=int,default=4,help="operator-owned full campaign concurrency budget")
 a=p.parse_args();paper_env=json.loads(a.orfs_agent_paper_environment.read_text()) if a.orfs_agent_paper_environment else None
 svc=WorkbenchService(a.state_root,backend=a.backend,rtl=a.rtl,top=a.top,design_id=a.design_id,platform_name=a.platform,clock_period_ns=a.clock_period_ns,orfs_agent_source=a.orfs_agent_source,orfs_agent_paper_orfs=a.orfs_agent_paper_orfs,orfs_agent_openroad_bin=a.orfs_agent_openroad_bin,orfs_agent_yosys_bin=a.orfs_agent_yosys_bin,orfs_agent_paper_environment=paper_env,a2_orfo_source=a.a2_orfo_source,a2_orfo_model=a.a2_orfo_model,a2_orfo_python=a.a2_orfo_python,a2_orfo_codex=a.a2_orfo_codex,l2_max_parallel=a.l2_max_parallel,model_provider=a.goal_provider,managed_reference=a.managed_reference)
 class H(BaseHTTPRequestHandler):
  def reply(self,x,code=200):
   b=json.dumps(x).encode();self.send_response(code);self.send_header("Content-Type","application/json");self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b)
  def do_POST(self):
   try:
    x=json.loads(self.rfile.read(int(self.headers.get("Content-Length",0)))); parts=self.path.strip("/").split("/")
    if self.path=="/api/l1/sessions": s=svc.start(x["text"], teaching_mode=x.get("teaching_mode", "guided")); return self.reply(s.to_dict())
    sid=parts[3]
    if parts[-1]=="answers": return self.reply(svc.answer(sid,x["answers"]).to_dict())
    if parts[-1]=="execute": p,state=svc.execute(sid,x["decision_summary"],wait=x.get("wait",True));return self.reply({"plan":p,"state":state.to_dict(),"runtime":svc.runtime.describe(p["run_id"])})
    if parts[-1]=="parameters": return self.reply(svc.set_flow_params(sid,x["values"],x["decision_summary"]))
    if parts[-1]=="m1-proposal": return self.reply(svc.propose_m1_candidate(sid))
    if parts[-1]=="candidates": p,state=svc.run_candidate(sid,x["proposal_id"],x["decision_summary"],wait=x.get("wait",True));return self.reply({"plan":p,"state":state.to_dict(),"runtime":svc.runtime.describe(p["run_id"])})
    if parts[-1]=="m1-compare": return self.reply(svc.compare_m1_candidate(sid,x["baseline_run_id"],x.get("decision_summary")))
    if parts[-1]=="l2-upgrade": return self.reply(svc.l2_upgrade(sid,wait=x.get("wait",False)))
    if parts[-1]=="l2-escalate": return self.reply(svc.l2_escalate(sid))
    if parts[-1]=="l2-configure": return self.reply(svc.l2_configure(sid,x["pipeline_id"],objective=x.get("objective","ECP"),initialization_seed=x.get("initialization_seed",401),screening_seed=x.get("screening_seed",401),confirmation_seeds=x.get("confirmation_seeds")))
    if parts[-1]=="l2-advance": return self.reply(svc.l2_advance(sid,x["pipeline_id"],execute=False,max_parallel=x.get("max_parallel",1)))
    if parts[-1]=="queries": return self.reply(svc.query(sid,x["kind"],x["decision_summary"],limit=x.get("limit",20)))
    if parts[-1]=="knowledge": return self.reply(svc.query_openroad_knowledge(sid,x["query"],x["decision_summary"],purpose=x.get("purpose","knowledge"),top_k=x.get("top_k",5)))
    if parts[-1]=="artifacts": return self.reply(svc.artifact_excerpt(sid,x["kind"],x["decision_summary"],max_bytes=x.get("max_bytes",4096)))
    if parts[-1]=="stages": p,state=svc.run_stage(sid,x["stage"],x["decision_summary"],wait=x.get("wait",True));return self.reply({"plan":p,"state":state.to_dict(),"runtime":svc.runtime.describe(p["run_id"])})
    if parts[-1]=="advance": return self.reply(svc.advance(sid))
    if parts[-1]=="cancel":return self.reply(svc.cancel(sid,x["reason"]))
    if parts[-1]=="recover":return self.reply(svc.recover(sid).to_dict())
    self.reply({"error":"not found"},404)
   except Exception as e:self.reply({"error":str(e)},400)
  def do_GET(self):
   try:
    parts=self.path.split("?")[0].strip("/").split("/")
    if parts[-1]=="teaching":
     return self.reply({"teaching":svc.teaching(parts[3])})
    if len(parts) >= 6 and parts[-2]=="l2-campaigns":
     return self.reply(svc.l2_status(parts[3],parts[-1]))
    if parts[-1]=="l2-campaigns":
     return self.reply({"l2_campaigns":svc.l2_list(parts[3])})
    q=parse_qs(urlparse(self.path).query);self.reply({"events":svc.events(parts[3],int(q.get("after",[-1])[0]))})
   except Exception as e:self.reply({"error":str(e)},400)
 ThreadingHTTPServer(("127.0.0.1",a.port),H).serve_forever()
if __name__=="__main__":main()
