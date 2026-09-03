"""Tutorial-shaped L1 smoke: language -> typed tools -> Runtime facts."""
from pathlib import Path
import platform
import sys
import hashlib

from openroad_platform_contracts import PluginManifest, TaskSpec
from openroad_platform_contracts.agent_control import AgentBudget, DesignState, GoalPreference, QoRConstraint, ToolName
from openroad_platform_contracts.l1_policy import TrustedPolicyIdentity
from openroad_platform_contracts.learning import EvidencePointer
from openroad_platform_execution import PluginRegistry, ProcessAdapter, ProcessGuardian
from openroad_platform_scheduler.l1_goal_finalizer import GoalFinalizer, TrustedGoalPolicy
from openroad_platform_scheduler.l1_loop import L1DurableLoop
from openroad_platform_scheduler.l1_loop_store import L1LoopStore
from openroad_platform_scheduler.l1_model_boundary import L1KnowledgeHit, L1ModelBoundary
from openroad_platform_scheduler.l1_runtime_bridge import L1RuntimeBridge
from openroad_platform_scheduler.l1_trace_service import L1TraceService
from openroad_platform_scheduler.l1_trace_store import L1TraceStore
from openroad_platform_scheduler.runtime import WorkflowRuntime
from openroad_platform_scheduler.runtime_store import RuntimeStore


class _Provider:
    provider_id = "tutorial_fixture_model"
    def __init__(self, responses): self.responses = iter(responses)
    def complete(self, request): return next(self.responses)

SOURCES = Path(__file__).parents[1] / "docs" / "evidence" / "l1_s6_tutorial_sources"

def _evidence(name):
    source = SOURCES / name
    return EvidencePointer(f"docs/evidence/l1_s6_tutorial_sources/{name}", hashlib.sha256(source.read_bytes()).hexdigest())

class _Retriever:
    def retrieve(self, query, *, limit):
        return (L1KnowledgeHit((SOURCES / "tutorial_knowledge.md").read_text(), _evidence("tutorial_knowledge.md")),)

class _Factory:
    capability = "eda.rtl_to_gds"
    def validate_task(self, task): task.validate()
    def reconfigure(self, task, values): return task

def test_tutorial_shaped_language_to_runtime_trace_smoke(tmp_path):
    fixture = Path(__file__).parent / "fixtures" / "echo_adapter.py"
    manifest = PluginManifest("tutorial-fixture", "1.0.0", (sys.executable, str(fixture)), ("eda.rtl_to_gds",), (platform.machine(),), {"type":"object"}, {"type":"object"}, ({"kind":"report","required":True},), 15)
    runtime = WorkflowRuntime(RuntimeStore(tmp_path / "runtime.sqlite"), PluginRegistry([manifest]), workspace_root=tmp_path / "work", adapter=ProcessAdapter(ProcessGuardian(poll_interval=0.01, terminate_grace=0.1)))
    provenance=_evidence("tutorial_policy.json")
    rtl=_evidence("tutorial_top.v")
    knowledge=_evidence("tutorial_knowledge.md")
    trusted=TrustedGoalPolicy("policy-1","v1","platform",provenance,"p1","top","tutorial-platform","pdk-1","toolchain-1",rtl,GoalPreference.BALANCED,(QoRConstraint("messages",">=",1),),("route",),("density",),AgentBudget(2,2,60),(ToolName.RUN_STAGE,ToolName.QUERY_STAGE_METRICS))
    model=_Provider([
        {"request_text":"Run a bounded route step then inspect its metrics.","intent":"diagnose","questions":[],"answers":[],"schema_version":1},
        {"call":{"call_id":"call-run","goal_id":"goal-1","state_id":"state-1","tool":"run_stage","arguments":{"stage":"route"},"producer":"tutorial_fixture_model","evidence":[knowledge.to_dict()],"schema_version":1},"decision_summary":"Run the permitted route stage to obtain Runtime facts.","citations":[knowledge.to_dict()]},
        {"call":{"call_id":"call-query","goal_id":"goal-1","state_id":"state-2","tool":"query_stage_metrics","arguments":{"run_id":"REPLACED"},"producer":"tutorial_fixture_model","evidence":[knowledge.to_dict()],"schema_version":1},"decision_summary":"Read registered metrics rather than infer QoR from raw logs.","citations":[knowledge.to_dict()]},
    ])
    draft=L1ModelBoundary.compile_draft(model,"Run a bounded route step then inspect its metrics.",draft_id="draft-1")
    goal=GoalFinalizer.finalize(draft,trusted,goal_id="goal-1")
    state1=DesignState("state-1","goal-1",0,"running",None,{},AgentBudget(2,2,60))
    trace=L1TraceService(L1TraceStore(tmp_path / "trace.sqlite")); trace.record_draft("trace-1",draft); trace.record_goal("trace-1",goal)
    bridge=L1RuntimeBridge(runtime,TaskSpec("tutorial-base","p1","top",plugin_id="tutorial-fixture",inputs={"message":"tutorial"},expected_artifacts=("report",),timeout_seconds=15),_Factory())
    loop=L1DurableLoop(L1LoopStore(tmp_path / "loop.sqlite"),bridge,trace)
    hits=L1ModelBoundary.retrieve(_Retriever(),"route timing")
    run=L1ModelBoundary.propose_tool(model,goal,state1,hits)
    plan=loop.plan_validate_execute("trace-1",goal,state1,run.call,TrustedPolicyIdentity("policy-1","v1","platform",provenance),planner_summary=run.decision_summary)
    runtime.execute_once(plan["run_id"])
    state2=loop.observe("trace-1",state1,plan["plan_id"],next_state_id="state-2")
    # Substitute only the Runtime-issued id into the third structured fixture.
    raw=next(model.responses); raw["call"]["arguments"]["run_id"]=plan["run_id"]
    model.responses=iter([raw])
    query=L1ModelBoundary.propose_tool(model,goal,state2,hits)
    loop.plan_validate_execute("trace-1",goal,state2,query.call,TrustedPolicyIdentity("policy-1","v1","platform",provenance),planner_summary=query.decision_summary)
    basis = tuple(event.event_id for event in trace.store.read("trace-1")
                  if event.kind.value in {"state_transition", "tool_receipt"})
    trace.record_reflection("trace-1",state2,summary="Registered Runtime metrics were observed; stop this bounded tutorial smoke.",decision="stop",evidence=query.citations,basis_event_ids=basis)
    events=trace.store.read("trace-1")
    assert state2.status == "observed" and any(event.kind.value == "state_transition" for event in events)
    assert events[-1].kind.value == "reflection_recorded" and events[-1].facts["decision"] == "stop"
    drafted, finalized = events[0], events[1]
    transition = next(event for event in events if event.kind.value == "state_transition")
    assert drafted.facts["request_text"] == "Run a bounded route step then inspect its metrics."
    assert drafted.facts["clarification_questions"] == [] and drafted.facts["clarification_answers"] == []
    assert finalized.facts["goal_ir"]["pdk_id"] == "pdk-1"
    assert transition.facts["state_before"]["status"] == "running"
    assert transition.facts["state_after"]["status"] == "observed"
    assert events[-1].facts["basis_event_ids"]
    for pointer in (knowledge, provenance, rtl):
        assert hashlib.sha256((Path(__file__).parents[1] / pointer.ref).read_bytes()).hexdigest() == pointer.sha256
