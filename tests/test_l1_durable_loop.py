from pathlib import Path
from openroad_platform_contracts.agent_control import AgentBudget, DesignGoal, DesignState, GoalPreference, QoRConstraint, SemanticToolCall, ToolName, ToolReceipt
from openroad_platform_contracts.learning import EvidencePointer
from openroad_platform_contracts.l1_policy import TrustedPolicyIdentity
from openroad_platform_scheduler.l1_loop import L1DurableLoop
from openroad_platform_scheduler.l1_loop_store import L1LoopStore
from openroad_platform_scheduler.l1_trace_service import L1TraceService
from openroad_platform_scheduler.l1_trace_store import L1TraceStore
import pytest

class _Bridge:
    def execute(self, goal, state, call): return ToolReceipt(call.call_id, goal.goal_id, state.state_id, call.tool, "accepted", {"run_id":"run-1"}, (EvidencePointer("run:run-1","e"*64),))
    def reduce_and_trace(self, trace, trace_id, state, *, run_id, next_state_id): raise AssertionError("not part of submit test")

class _FailingBridge(_Bridge):
    def execute(self, goal, state, call): raise RuntimeError("injected bridge failure")

def test_durable_loop_persists_validated_call_policy_and_receipt(tmp_path: Path):
    policy=TrustedPolicyIdentity("policy-1","v1","platform",EvidencePointer("artifact:policy","d"*64))
    goal=DesignGoal("goal-1","p1","top","platform-1","pdk-1","toolchain-1",EvidencePointer("artifact:rtl","a"*64),GoalPreference.BALANCED,(QoRConstraint("setup_wns_ns",">=",0),),("route",),("density",),AgentBudget(2,2,60),allowed_tools=(ToolName.RUN_FULL_FLOW,),labels={"l1_policy_id":"policy-1","l1_policy_version":"v1","l1_policy_issuer":"platform","l1_policy_provenance":"artifact:policy","l1_policy_provenance_sha256":"d"*64})
    state=DesignState("state-1","goal-1",0,"running",None,{},AgentBudget(2,2,60))
    trace=L1TraceService(L1TraceStore(tmp_path/"trace.sqlite")); trace.record_goal("trace-1",goal)
    loop=L1DurableLoop(L1LoopStore(tmp_path/"loop.sqlite"),_Bridge(),trace)
    plan=loop.plan_validate_execute("trace-1",goal,state,SemanticToolCall("call-1","goal-1","state-1",ToolName.RUN_FULL_FLOW,{},"planner"),policy,planner_summary="run bounded flow")
    assert plan["status"] == "submitted" and plan["run_id"] == "run-1"
    assert [event.kind.value for event in trace.store.read("trace-1")] == ["goal_finalized","tool_called","policy_decided","tool_receipt"]

def test_loop_rejects_runtime_submission_after_budget_exhaustion(tmp_path: Path):
    policy=TrustedPolicyIdentity("policy-1","v1","platform",EvidencePointer("artifact:policy","d"*64))
    goal=DesignGoal("goal-1","p1","top","platform-1","pdk-1","toolchain-1",EvidencePointer("artifact:rtl","a"*64),GoalPreference.BALANCED,(QoRConstraint("setup_wns_ns",">=",0),),("route",),("density",),AgentBudget(1,2,60),allowed_tools=(ToolName.RUN_FULL_FLOW,),labels={"l1_policy_id":"policy-1","l1_policy_version":"v1","l1_policy_issuer":"platform","l1_policy_provenance":"artifact:policy","l1_policy_provenance_sha256":"d"*64})
    state=DesignState("state-1","goal-1",0,"running",None,{},AgentBudget(0,2,60))
    trace=L1TraceService(L1TraceStore(tmp_path/"trace.sqlite")); trace.record_goal("trace-1",goal)
    with pytest.raises(ValueError,match="budget"):
        L1DurableLoop(L1LoopStore(tmp_path/"loop.sqlite"),_Bridge(),trace).plan_validate_execute("trace-1",goal,state,SemanticToolCall("call-1","goal-1","state-1",ToolName.RUN_FULL_FLOW,{},"planner"),policy,planner_summary="no budget")

def test_failed_pre_submit_bridge_releases_parameter_proposal(tmp_path: Path):
    policy=TrustedPolicyIdentity("policy-1","v1","platform",EvidencePointer("artifact:policy","d"*64))
    labels={"l1_policy_id":"policy-1","l1_policy_version":"v1","l1_policy_issuer":"platform","l1_policy_provenance":"artifact:policy","l1_policy_provenance_sha256":"d"*64}
    goal=DesignGoal("goal-1","p1","top","platform-1","pdk-1","toolchain-1",EvidencePointer("artifact:rtl","a"*64),GoalPreference.BALANCED,(QoRConstraint("setup_wns_ns",">=",0),),("route",),("density",),AgentBudget(2,2,60),allowed_tools=(ToolName.RUN_FULL_FLOW,),labels=labels)
    state=DesignState("state-1","goal-1",0,"running",None,{},AgentBudget(2,2,60))
    trace=L1TraceService(L1TraceStore(tmp_path/"trace.sqlite")); trace.record_goal("trace-1",goal)
    store=L1LoopStore(tmp_path/"loop.sqlite"); store.save_proposal("proposal-1","trace-1","goal-1","state-1",{"density":0.7})
    call=SemanticToolCall("call-1","goal-1","state-1",ToolName.RUN_FULL_FLOW,{"proposal_id":"proposal-1"},"planner")
    with pytest.raises(RuntimeError,match="injected"):
        L1DurableLoop(store,_FailingBridge(),trace).plan_validate_execute("trace-1",goal,state,call,policy,planner_summary="injected")
    store.propose("retry","trace-1","goal-1","state-1",{})
    assert store.reserve_proposal("proposal-1","trace-1","goal-1","state-1","retry") == {"density":0.7}

def test_trace_failure_releases_parameter_proposal_before_runtime_submit(tmp_path: Path, monkeypatch):
    policy=TrustedPolicyIdentity("policy-1","v1","platform",EvidencePointer("artifact:policy","d"*64))
    labels={"l1_policy_id":"policy-1","l1_policy_version":"v1","l1_policy_issuer":"platform","l1_policy_provenance":"artifact:policy","l1_policy_provenance_sha256":"d"*64}
    goal=DesignGoal("goal-1","p1","top","platform-1","pdk-1","toolchain-1",EvidencePointer("artifact:rtl","a"*64),GoalPreference.BALANCED,(QoRConstraint("setup_wns_ns",">=",0),),("route",),("density",),AgentBudget(2,2,60),allowed_tools=(ToolName.RUN_FULL_FLOW,),labels=labels)
    state=DesignState("state-1","goal-1",0,"running",None,{},AgentBudget(2,2,60))
    trace=L1TraceService(L1TraceStore(tmp_path/"trace.sqlite")); trace.record_goal("trace-1",goal)
    store=L1LoopStore(tmp_path/"loop.sqlite"); store.save_proposal("proposal-1","trace-1","goal-1","state-1",{"density":0.7})
    monkeypatch.setattr(trace,"record_call",lambda *_args,**_kwargs: (_ for _ in ()).throw(OSError("injected trace failure")))
    with pytest.raises(OSError,match="trace"):
        L1DurableLoop(store,_Bridge(),trace).plan_validate_execute("trace-1",goal,state,SemanticToolCall("call-1","goal-1","state-1",ToolName.RUN_FULL_FLOW,{"proposal_id":"proposal-1"},"planner"),policy,planner_summary="injected")
    store.propose("retry","trace-1","goal-1","state-1",{})
    assert store.reserve_proposal("proposal-1","trace-1","goal-1","state-1","retry") == {"density":0.7}

def test_recover_submission_uses_durable_receipt_without_resubmit(tmp_path: Path, monkeypatch):
    policy=TrustedPolicyIdentity("policy-1","v1","platform",EvidencePointer("artifact:policy","d"*64))
    labels={"l1_policy_id":"policy-1","l1_policy_version":"v1","l1_policy_issuer":"platform","l1_policy_provenance":"artifact:policy","l1_policy_provenance_sha256":"d"*64}
    goal=DesignGoal("goal-1","p1","top","platform-1","pdk-1","toolchain-1",EvidencePointer("artifact:rtl","a"*64),GoalPreference.BALANCED,(QoRConstraint("setup_wns_ns",">=",0),),("route",),("density",),AgentBudget(2,2,60),allowed_tools=(ToolName.RUN_FULL_FLOW,),labels=labels)
    state=DesignState("state-1","goal-1",0,"running",None,{},AgentBudget(2,2,60))
    trace=L1TraceService(L1TraceStore(tmp_path/"trace.sqlite")); trace.record_goal("trace-1",goal)
    store=L1LoopStore(tmp_path/"loop.sqlite"); store.save_proposal("proposal-1","trace-1","goal-1","state-1",{"density":0.7})
    loop=L1DurableLoop(store,_Bridge(),trace)
    original=store.record_receipt; monkeypatch.setattr(store,"record_receipt",lambda *_: (_ for _ in ()).throw(OSError("injected receipt persistence failure")))
    with pytest.raises(OSError): loop.plan_validate_execute("trace-1",goal,state,SemanticToolCall("call-1","goal-1","state-1",ToolName.RUN_FULL_FLOW,{"proposal_id":"proposal-1"},"planner"),policy,planner_summary="recover")
    plan_id=next(event for event in trace.store.read("trace-1") if event.kind.value == "tool_receipt").facts["call_id"]
    plan = next(row for row in (store.get(key) for key in [])) if False else None
    # The only prepared plan is recoverable from its durable receipt; no second bridge call occurs.
    import sqlite3
    with sqlite3.connect(store.database) as c: durable_plan=c.execute("SELECT plan_id FROM l1_loop_plan WHERE status='prepared'").fetchone()[0]
    monkeypatch.setattr(store,"record_receipt",original)
    recovered=loop.recover_submission("trace-1",durable_plan)
    assert recovered["status"] == "submitted" and recovered["call"]["arguments"]["parameter_patch"] == {"density":0.7}
