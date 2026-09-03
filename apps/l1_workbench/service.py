"""Operational L1 vertical slice; transport/UI are deliberately absent."""
from __future__ import annotations
import json, platform, sqlite3, sys, uuid, threading
from pathlib import Path
from dataclasses import replace
from typing import Any

from openroad_platform_contracts import PluginManifest, RTLToGDSRequest, TaskSpec
from openroad_platform_contracts.agent_control import AgentBudget, DesignState, GoalPreference, QoRConstraint, SemanticToolCall, ToolName
from openroad_platform_contracts.l1_goal_draft import ClarificationAnswer, ClarificationField
from openroad_platform_contracts.l1_policy import TrustedPolicyIdentity
from openroad_platform_contracts.learning import EvidencePointer
from openroad_platform_execution import (ORFSRTLToGDSFactory, PluginRegistry,
    ProcessAdapter, ProcessGuardian, ToolchainConfig, orfs_plugin_manifest)
from openroad_platform_scheduler.l1_goal_finalizer import TrustedGoalPolicy
from openroad_platform_scheduler.l1_loop import L1DurableLoop
from openroad_platform_scheduler.l1_loop_store import L1LoopStore
from openroad_platform_scheduler.l1_runtime_bridge import L1RuntimeBridge
from openroad_platform_scheduler.l1_session_service import L1SessionService, L1SessionStore
from openroad_platform_scheduler.l1_trace_service import L1TraceService
from openroad_platform_scheduler.l1_trace_store import L1TraceStore
from openroad_platform_scheduler.runtime import WorkflowRuntime
from openroad_platform_scheduler.runtime_store import RuntimeStore

class _Provider:
    provider_id = "l1-workbench-deterministic-v1"
    def __init__(self, clarification_prompt="Confirm this bounded Runtime tool execution."): self.clarification_prompt=clarification_prompt
    def complete(self, request):
        if request["kind"] == "goal_draft":
            return {"schema_version":1,"request_text": request["request_text"], "intent": "execute", "answers": [], "questions": [{"schema_version":1,"question_id":"objective-1","field":"objective","prompt":self.clarification_prompt,"blocking":True}]}
        prior=request["prior_draft"]; return {"schema_version":1,"request_text":prior["request_text"],"intent":"execute","questions":prior["questions"],"answers":request["answers"]}

class WorkbenchService:
    """L1 composition root; ``orfs`` binds its typed loop to real EDA."""
    def __init__(self, root: str | Path, *, backend="smoke", rtl=None,
                 top="mux_2to1", platform_name="nangate45", clock_period_ns=10.0):
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
        if backend not in {"smoke", "orfs"}: raise ValueError("backend must be smoke or orfs")
        self.backend, self.rtl, self.top = backend, Path(rtl).expanduser().resolve() if rtl else None, top
        self.platform_name, self.clock_period_ns = platform_name, clock_period_ns
        self.trace=L1TraceService(L1TraceStore(self.root/"trace.sqlite")); self.sessions=L1SessionService(L1SessionStore(self.root/"sessions.sqlite"),self.trace)
        if backend == "orfs":
            if self.rtl is None or not self.rtl.is_file(): raise FileNotFoundError("ORFS workbench requires frozen RTL")
            self.toolchain=ToolchainConfig.from_environment(name="orfs-2d-baseline"); self.toolchain.validate()
            self.factory=ORFSRTLToGDSFactory(); manifest=orfs_plugin_manifest(self.toolchain, default_timeout_seconds=7200)
        else:
            self.toolchain=None; self.factory=None
            manifest=PluginManifest("l1-runtime-smoke","1",(sys.executable,str(Path(__file__).with_name("runtime_adapter.py"))),("eda.rtl_to_gds",),(platform.machine(),),{"type":"object"},{"type":"object"},({"kind":"report","required":True},),30)
        self.runtime=WorkflowRuntime(RuntimeStore(self.root/"runtime.sqlite"),PluginRegistry([manifest]),workspace_root=self.root/"work",adapter=ProcessAdapter(ProcessGuardian(poll_interval=.01,terminate_grace=.1)))
        self.loop_store=L1LoopStore(self.root/"loop.sqlite")
        with sqlite3.connect(self.root/"workbench.sqlite") as c: c.execute("CREATE TABLE IF NOT EXISTS session_state(session_id TEXT PRIMARY KEY,state_json TEXT,plan_id TEXT)")
    def policy(self):
        evidence=EvidencePointer("artifact:workbench-rtl","a"*64); provenance=EvidencePointer("artifact:workbench-policy","b"*64)
        if self.backend == "orfs":
            import hashlib
            digest=hashlib.sha256(self.rtl.read_bytes()).hexdigest(); evidence=EvidencePointer(f"artifact:rtl-{digest[:12]}",digest)
            return TrustedGoalPolicy("l1-orfs-baseline-policy","v1","platform",provenance,"tutorial_mux","mux_2to1",self.platform_name,self.platform_name,self.toolchain.name,evidence,GoalPreference.BALANCED,(QoRConstraint("l1_tool_runs",">=",1),),("finish",),("core_utilization_pct","place_density","minimum_die_size_um"),AgentBudget(1,4,7200),(ToolName.RUN_FULL_FLOW,ToolName.STOP_OR_ESCALATE))
        return TrustedGoalPolicy("workbench-policy","v1","platform",provenance,"workbench-project","workbench-design","workbench","workbench-pdk","workbench-toolchain",evidence,GoalPreference.BALANCED,(QoRConstraint("l1_tool_runs",">=",1),),("finish",),("density",),AgentBudget(1,4,30),(ToolName.RUN_FULL_FLOW,ToolName.STOP_OR_ESCALATE))
    def start(self, text):
        prompt=(f"Confirm baseline implementation of frozen {self.top} RTL on {self.platform_name}, "
                f"clock period {self.clock_period_ns} ns. This will run the admitted local ORFS/OpenROAD toolchain."
                if self.backend == "orfs" else "Confirm this bounded Runtime tool execution.")
        return self.sessions.start(text,_Provider(prompt),self.policy())
    def answer(self,sid,answers):
        rows=tuple(ClarificationAnswer(a["question_id"],ClarificationField(a["field"]),a["value"]) for a in answers); session=self.sessions.answer(sid,_Provider(),rows)
        if session.goal_id:
            policy=self.policy()
            self._save(sid,DesignState(f"state-{uuid.uuid4().hex}",session.goal_id,0,"running",None,{},policy.budget,evidence=(policy.rtl_artifact,)),None)
        return session
    def execute(self,sid,summary,*,wait=True):
        session=self.sessions.store.get(sid); goal=self._goal(session.trace_id,session.goal_id); state, _=self._load(sid)
        if self.backend == "orfs":
            task=self.factory.build(RTLToGDSRequest(rtl_path=str(self.rtl),project_id=goal.project_id,design_id=goal.design_id,top=self.top,task_id=f"l1-orfs-{uuid.uuid4().hex}",labels={"surface":"l1-workbench","mode":"baseline"},options={"platform_name":self.platform_name,"target_stage":"finish","clock_period_ns":self.clock_period_ns,"core_utilization_pct":10.0,"place_density":0.45,"stage_timeout_seconds":3600,"timeout_seconds":7200}))
            factory=self.factory
        else:
            task=TaskSpec(f"l1-workbench-{uuid.uuid4().hex}",goal.project_id,goal.design_id,plugin_id="l1-runtime-smoke",inputs={"kind":"bounded_l1_tool","bounded_mode":"normal" if wait else "cancellable"},expected_artifacts=("report",),timeout_seconds=30)
            class Factory:
                capability="eda.rtl_to_gds"
                def validate_task(self,t): t.validate()
                def reconfigure(self,t,v): return t
            factory=Factory()
        bridge=L1RuntimeBridge(self.runtime,task,factory,cancel_port=self.runtime.store.request_cancel)
        loop=L1DurableLoop(self.loop_store,bridge,self.trace); call=SemanticToolCall(f"call-{uuid.uuid4().hex}",goal.goal_id,state.state_id,ToolName.RUN_FULL_FLOW,{},"l1-workbench")
        trusted=self.policy(); identity=TrustedPolicyIdentity(trusted.policy_id,trusted.policy_version,trusted.issuer,trusted.provenance)
        plan=loop.plan_validate_execute(session.trace_id,goal,state,call,identity,planner_summary=summary)
        self._save(sid,state,plan["plan_id"])
        def finish():
            self.runtime.execute_once(plan["run_id"])
            successor=loop.observe(session.trace_id,state,plan["plan_id"],next_state_id=f"state-{uuid.uuid4().hex}")
            self._save(sid,successor,plan["plan_id"])
        if wait: finish(); return plan, self._load(sid)[0]
        threading.Thread(target=finish,daemon=True).start(); return plan, state
    def cancel(self,sid,reason):
        state,plan=self._load(sid); self.runtime.store.request_cancel(self.loop_store.get(plan)["run_id"]); return {"status":"cancel_requested","reason":reason}
    def recover(self,sid):
        session=self.sessions.recover(sid); state,plan=self._load(sid)
        if plan and self.loop_store.get(plan)["status"]=="prepared": self.loop_store.get(plan)
        return session
    def events(self,sid,after=-1): return [e.to_dict() for e in self.sessions.events(sid,after_sequence=after)]
    def _goal(self,trace_id,gid):
        from openroad_platform_contracts.agent_control import DesignGoal
        return DesignGoal.from_dict(next(e.facts["goal_ir"] for e in self.trace.store.read(trace_id) if e.goal_id==gid and e.kind.value=="goal_finalized"))
    def _save(self,sid,state,plan):
        with sqlite3.connect(self.root/"workbench.sqlite") as c:c.execute("INSERT OR REPLACE INTO session_state VALUES(?,?,?)",(sid,json.dumps(state.to_dict()),plan))
    def _load(self,sid):
        with sqlite3.connect(self.root/"workbench.sqlite") as c:r=c.execute("SELECT state_json,plan_id FROM session_state WHERE session_id=?",(sid,)).fetchone()
        if not r: raise ValueError("session has no finalized Goal state")
        return DesignState.from_dict(json.loads(r[0])),r[1]
