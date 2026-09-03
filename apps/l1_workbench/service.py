"""Operational L1 vertical slice; transport/UI are deliberately absent."""
from __future__ import annotations
import json, platform, sqlite3, sys, uuid, threading
from pathlib import Path
from dataclasses import replace
from typing import Any

from openroad_platform_contracts import PluginManifest, RTLToGDSRequest, TaskSpec
from openroad_platform_contracts.agent_control import DEFAULT_L1_TOOLS, AgentBudget, DesignState, GoalPreference, QoRConstraint, SemanticToolCall, ToolName
from openroad_platform_contracts.l1_goal_draft import ClarificationAnswer, ClarificationField, ClarificationQuestion
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
try:
    from .tutorial_profile import ManagedTutorialProfile
    from .tutorial_planner import TutorialEvidencePlanner
except ImportError:  # Direct ``python apps/l1_workbench/server.py`` launch.
    from tutorial_profile import ManagedTutorialProfile
    from tutorial_planner import TutorialEvidencePlanner

class _Provider:
    provider_id = "l1-workbench-deterministic-v1"
    def __init__(self, questions=()): self.questions=tuple(questions)
    def complete(self, request):
        if request["kind"] == "goal_draft":
            questions = self.questions or (ClarificationQuestion("objective-1", ClarificationField.OBJECTIVE, "Confirm this bounded Runtime tool execution.", True),)
            return {"schema_version":1,"request_text": request["request_text"], "intent": "execute", "answers": [], "questions": [item.to_dict() for item in questions]}
        prior=request["prior_draft"]; return {"schema_version":1,"request_text":prior["request_text"],"intent":"execute","questions":prior["questions"],"answers":request["answers"]}

class WorkbenchService:
    """L1 composition root; ``orfs`` binds its typed loop to real EDA."""
    def __init__(self, root: str | Path, *, backend="smoke", rtl=None,
                 top="mux_2to1", platform_name="nangate45", clock_period_ns=10.0):
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
        if backend not in {"smoke", "orfs"}: raise ValueError("backend must be smoke or orfs")
        self.backend, self.rtl, self.top = backend, Path(rtl).expanduser().resolve() if rtl else None, top
        self.platform_name, self.clock_period_ns = platform_name, clock_period_ns
        self.trace=L1TraceService(L1TraceStore(self.root/"trace.sqlite"))
        if backend == "orfs":
            if self.rtl is None or not self.rtl.is_file(): raise FileNotFoundError("ORFS workbench requires frozen RTL")
            self.toolchain=ToolchainConfig.from_environment(name="orfs-2d-baseline"); self.toolchain.validate()
            self.factory=ORFSRTLToGDSFactory(); manifest=orfs_plugin_manifest(self.toolchain, default_timeout_seconds=7200)
        else:
            self.toolchain=None; self.factory=None
            manifest=PluginManifest("l1-runtime-smoke","1",(sys.executable,str(Path(__file__).with_name("runtime_adapter.py"))),("eda.rtl_to_gds",),(platform.machine(),),{"type":"object"},{"type":"object"},({"kind":"report","required":True},),30)
        self.profile=ManagedTutorialProfile() if backend == "orfs" else None
        self.sessions=L1SessionService(L1SessionStore(self.root/"sessions.sqlite"),self.trace,
                                       goal_finalizer=self.profile.compile if self.profile else None)
        self.runtime=WorkflowRuntime(RuntimeStore(self.root/"runtime.sqlite"),PluginRegistry([manifest]),workspace_root=self.root/"work",adapter=ProcessAdapter(ProcessGuardian(poll_interval=.01,terminate_grace=.1)))
        self.loop_store=L1LoopStore(self.root/"loop.sqlite")
        with sqlite3.connect(self.root/"workbench.sqlite") as c: c.execute("CREATE TABLE IF NOT EXISTS session_state(session_id TEXT PRIMARY KEY,state_json TEXT,plan_id TEXT)")
    def policy(self):
        evidence=EvidencePointer("artifact:workbench-rtl","a"*64); provenance=EvidencePointer("artifact:workbench-policy","b"*64)
        if self.backend == "orfs":
            import hashlib
            digest=hashlib.sha256(self.rtl.read_bytes()).hexdigest(); evidence=EvidencePointer(f"artifact:rtl-{digest[:12]}",digest)
            return TrustedGoalPolicy("l1-orfs-baseline-policy","v1","platform",provenance,"tutorial_mux","mux_2to1",self.platform_name,self.platform_name,self.toolchain.name,evidence,GoalPreference.BALANCED,(QoRConstraint("l1_tool_runs",">=",1),),("synth","floorplan","place","cts","route","finish"),("core_utilization_pct","place_density","minimum_die_size_um"),AgentBudget(3,4,7200),DEFAULT_L1_TOOLS)
        return TrustedGoalPolicy("workbench-policy","v1","platform",provenance,"workbench-project","workbench-design","workbench","workbench-pdk","workbench-toolchain",evidence,GoalPreference.BALANCED,(QoRConstraint("l1_tool_runs",">=",1),),("finish",),("density",),AgentBudget(1,4,30),DEFAULT_L1_TOOLS)
    def start(self, text):
        return self.sessions.start(text,_Provider(self.profile.questions() if self.profile else ()),self.policy())
    def answer(self,sid,answers):
        rows=tuple(ClarificationAnswer(a["question_id"],ClarificationField(a["field"]),a["value"]) for a in answers); session=self.sessions.answer(sid,_Provider(),rows)
        if session.goal_id:
            goal=self._goal(session.trace_id,session.goal_id)
            self._save(sid,DesignState(f"state-{uuid.uuid4().hex}",session.goal_id,0,"running",None,{},goal.budget,evidence=(goal.rtl_artifact,)),None)
        return session
    def _bridge(self, goal, *, wait=True, target_stage="finish"):
        """Build an immutable base TaskSpec; Runtime remains the run authority."""
        if self.backend == "orfs":
            if target_stage not in goal.allowed_stages: raise ValueError("stage is outside the finalized Goal")
            task=self.factory.build(RTLToGDSRequest(rtl_path=str(self.rtl),project_id=goal.project_id,design_id=goal.design_id,top=self.top,task_id=f"l1-orfs-{uuid.uuid4().hex}",labels={"surface":"l1-workbench","mode":"baseline"},options={"platform_name":self.platform_name,"target_stage":target_stage,"clock_period_ns":self.clock_period_ns,"core_utilization_pct":10.0,"place_density":0.45,"stage_timeout_seconds":3600,"timeout_seconds":7200}))
            factory=self.factory
        else:
            task=TaskSpec(f"l1-workbench-{uuid.uuid4().hex}",goal.project_id,goal.design_id,plugin_id="l1-runtime-smoke",inputs={"kind":"bounded_l1_tool","bounded_mode":"normal" if wait else "cancellable"},expected_artifacts=("report",),timeout_seconds=30)
            class Factory:
                capability="eda.rtl_to_gds"
                def validate_task(self,t): t.validate()
                def reconfigure(self,t,v): return t
            factory=Factory()
        return L1RuntimeBridge(self.runtime,task,factory,cancel_port=self.runtime.store.request_cancel)
    def execute(self,sid,summary,*,wait=True):
        session=self.sessions.store.get(sid); goal=self._goal(session.trace_id,session.goal_id); state, _=self._load(sid)
        bridge=self._bridge(goal,wait=wait)
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
    def query(self,sid,kind,summary,*,limit=20):
        """Read only the current Goal-owned Runtime result through typed tools."""
        session=self.sessions.store.get(sid); goal=self._goal(session.trace_id,session.goal_id); state, _=self._load(sid)
        run_id=state.diagnosis.get("runtime_run_id")
        if not isinstance(run_id,str) or not run_id: raise ValueError("query requires an observed Runtime run for this Session")
        tools={"timing":ToolName.QUERY_TIMING,"congestion":ToolName.QUERY_CONGESTION,
               "drc":ToolName.QUERY_DRC,"power":ToolName.QUERY_POWER,
               "metrics":ToolName.QUERY_STAGE_METRICS}
        try: tool=tools[kind]
        except KeyError as exc: raise ValueError("unknown L1 query kind") from exc
        if not isinstance(limit,int) or isinstance(limit,bool) or not 1 <= limit <= 256: raise ValueError("query limit is invalid")
        bridge=self._bridge(goal); loop=L1DurableLoop(self.loop_store,bridge,self.trace)
        call=SemanticToolCall(f"call-{uuid.uuid4().hex}",goal.goal_id,state.state_id,tool,{"run_id":run_id,"limit":limit},"l1-workbench")
        trusted=self.policy(); identity=TrustedPolicyIdentity(trusted.policy_id,trusted.policy_version,trusted.issuer,trusted.provenance)
        return loop.plan_validate_execute(session.trace_id,goal,state,call,identity,planner_summary=summary)
    def artifact_excerpt(self,sid,kind,summary,*,max_bytes=4096):
        """Read one registered artifact by approved kind, never by path."""
        session=self.sessions.store.get(sid); goal=self._goal(session.trace_id,session.goal_id); state, _=self._load(sid)
        run_id=state.diagnosis.get("runtime_run_id")
        if not isinstance(run_id,str) or not run_id: raise ValueError("artifact query requires an observed Runtime run")
        if not isinstance(kind,str) or kind not in {"report","log","run_result","config"}: raise ValueError("artifact kind is not exposed by the L1 tutorial")
        if not isinstance(max_bytes,int) or isinstance(max_bytes,bool) or not 1 <= max_bytes <= 64 * 1024: raise ValueError("artifact excerpt size is invalid")
        view=self.runtime.describe(run_id)
        matches=[item for stage in view.get("stages",()) for attempt in stage.get("attempts",()) for item in attempt.get("artifacts",()) if item.get("kind")==kind]
        if not matches: raise ValueError("current Runtime run has no registered requested artifact kind")
        artifact_id=matches[0].get("artifact_id")
        if not isinstance(artifact_id,str) or not artifact_id: raise ValueError("registered artifact is missing its identity")
        bridge=self._bridge(goal); loop=L1DurableLoop(self.loop_store,bridge,self.trace)
        call=SemanticToolCall(f"call-{uuid.uuid4().hex}",goal.goal_id,state.state_id,ToolName.QUERY_ARTIFACT_EXCERPT,{"run_id":run_id,"artifact_id":artifact_id,"offset":0,"max_bytes":max_bytes},"l1-workbench")
        trusted=self.policy(); identity=TrustedPolicyIdentity(trusted.policy_id,trusted.policy_version,trusted.issuer,trusted.provenance)
        return loop.plan_validate_execute(session.trace_id,goal,state,call,identity,planner_summary=summary)
    def run_stage(self,sid,stage,summary,*,wait=True):
        """Submit one allowed ORFS stage under the same Runtime lifecycle."""
        session=self.sessions.store.get(sid); goal=self._goal(session.trace_id,session.goal_id); state, _=self._load(sid)
        bridge=self._bridge(goal,wait=wait,target_stage=stage); loop=L1DurableLoop(self.loop_store,bridge,self.trace)
        call=SemanticToolCall(f"call-{uuid.uuid4().hex}",goal.goal_id,state.state_id,ToolName.RUN_STAGE,{"stage":stage},"l1-workbench")
        trusted=self.policy(); identity=TrustedPolicyIdentity(trusted.policy_id,trusted.policy_version,trusted.issuer,trusted.provenance)
        plan=loop.plan_validate_execute(session.trace_id,goal,state,call,identity,planner_summary=summary)
        self._save(sid,state,plan["plan_id"])
        def finish():
            self.runtime.execute_once(plan["run_id"])
            successor=loop.observe(session.trace_id,state,plan["plan_id"],next_state_id=f"state-{uuid.uuid4().hex}")
            self._save(sid,successor,plan["plan_id"])
        if wait: finish(); return plan,self._load(sid)[0]
        threading.Thread(target=finish,daemon=True).start(); return plan,state
    def advance(self,sid):
        """Execute one evidence-backed tutorial decision; never accept a shell action."""
        session=self.sessions.store.get(sid); goal=self._goal(session.trace_id,session.goal_id); state,_=self._load(sid)
        decision=TutorialEvidencePlanner.choose(goal,state,self.events(sid))
        payload={"decision":{"action":decision.action,"summary":decision.summary,"hypothesis":decision.hypothesis,"basis_event_ids":list(decision.basis_event_ids)}}
        if decision.action == "run_full_flow":
            plan,next_state=self.execute(sid,decision.summary); payload.update({"plan":plan,"state":next_state.to_dict()})
        elif decision.action == "query_timing":
            payload["plan"]=self.query(sid,"timing",decision.summary)
        elif decision.action == "reflect_continue":
            event=self.trace.record_reflection(session.trace_id,state,summary=decision.summary,decision="continue",evidence=state.evidence,hypotheses=decision.hypothesis,basis_event_ids=decision.basis_event_ids)
            payload["reflection_event_id"]=event.event_id
        elif decision.action == "run_route":
            plan,next_state=self.run_stage(sid,"route",decision.summary); payload.update({"plan":plan,"state":next_state.to_dict()})
        elif decision.action == "query_drc":
            payload["plan"]=self.query(sid,"drc",decision.summary)
        elif decision.action == "stop":
            event=self.trace.record_reflection(session.trace_id,state,summary=decision.summary,decision="stop",evidence=state.evidence,hypotheses=decision.hypothesis,basis_event_ids=decision.basis_event_ids)
            payload["reflection_event_id"]=event.event_id
        else: raise RuntimeError("tutorial planner returned an unsupported action")
        return payload
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
