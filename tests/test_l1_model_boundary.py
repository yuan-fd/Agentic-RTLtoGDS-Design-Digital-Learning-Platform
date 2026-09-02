import pytest

from openroad_platform_contracts.agent_control import AgentBudget, DesignGoal, DesignState, GoalPreference, QoRConstraint, ToolName
from openroad_platform_contracts.learning import EvidencePointer
from openroad_platform_scheduler.l1_model_boundary import L1KnowledgeHit, L1ModelBoundary


class _Provider:
    provider_id = "fixture_provider"
    def __init__(self, response): self.response = response
    def complete(self, request): return self.response

class _Retriever:
    def retrieve(self, query, *, limit): return (L1KnowledgeHit("Timing report guidance", EvidencePointer("docs/evidence/tutorial", "e" * 64)),)

def _goal_state():
    goal=DesignGoal("goal-1","p1","top","platform-1","pdk-1","toolchain-1",EvidencePointer("artifact:rtl","a"*64),GoalPreference.BALANCED,(QoRConstraint("setup_wns_ns",">=",0),),("route",),("density",),AgentBudget(2,2,60),allowed_tools=(ToolName.QUERY_TIMING,))
    return goal, DesignState("state-1","goal-1",0,"running",None,{},AgentBudget(2,2,60))

def test_model_boundary_compiles_only_typed_draft_and_preserves_request():
    provider=_Provider({"request_text":"diagnose timing","intent":"diagnose","questions":[],"answers":[],"schema_version":1})
    draft=L1ModelBoundary.compile_draft(provider,"diagnose timing",draft_id="draft-1")
    assert draft.parser_id == "fixture_provider" and draft.request_sha256
    with pytest.raises(ValueError,match="changed"):
        L1ModelBoundary.compile_draft(_Provider({"request_text":"other","intent":"diagnose","questions":[],"answers":[],"schema_version":1}),"diagnose timing",draft_id="draft-1")
    with pytest.raises(ValueError,match="forbidden"):
        L1ModelBoundary.compile_draft(_Provider({"request_text":"diagnose timing","intent":"diagnose","questions":[],"answers":[],"tcl":"report_timing","schema_version":1}),"diagnose timing",draft_id="draft-1")

def test_model_boundary_rejects_shell_and_unretrieved_citations():
    goal,state=_goal_state(); hits=L1ModelBoundary.retrieve(_Retriever(),"timing")
    malicious={"call":{"call_id":"call-1","goal_id":"goal-1","state_id":"state-1","tool":"query_timing","arguments":{"run_id":"run-1","shell":"rm"},"producer":"model","evidence":[],"schema_version":1},"decision_summary":"inspect timing","citations":[hits[0].evidence.to_dict()]}
    with pytest.raises(ValueError,match="forbidden"):
        L1ModelBoundary.propose_tool(_Provider(malicious),goal,state,hits)
    tcl={"call":{"call_id":"call-1","goal_id":"goal-1","state_id":"state-1","tool":"query_timing","arguments":{"run_id":"run-1","nested":[[{"tclScript":"report_timing"}]]},"producer":"model","evidence":[],"schema_version":1},"decision_summary":"inspect timing","citations":[hits[0].evidence.to_dict()]}
    with pytest.raises(ValueError,match="forbidden"):
        L1ModelBoundary.propose_tool(_Provider(tcl),goal,state,hits)
    uncited={"call":{"call_id":"call-1","goal_id":"goal-1","state_id":"state-1","tool":"query_timing","arguments":{"run_id":"run-1"},"producer":"model","evidence":[],"schema_version":1},"decision_summary":"inspect timing","citations":[{"ref":"docs/evidence/other","sha256":"f"*64,"schema_version":1}]}
    with pytest.raises(ValueError,match="not returned"):
        L1ModelBoundary.propose_tool(_Provider(uncited),goal,state,hits)

def test_model_boundary_validates_tool_against_finalized_goal_policy():
    goal,state=_goal_state(); hits=L1ModelBoundary.retrieve(_Retriever(),"timing")
    raw={"call":{"call_id":"call-1","goal_id":"goal-1","state_id":"state-1","tool":"query_timing","arguments":{"run_id":"run-1"},"producer":"model","evidence":[hits[0].evidence.to_dict()],"schema_version":1},"decision_summary":"inspect artifact-backed timing facts","citations":[hits[0].evidence.to_dict()]}
    proposal=L1ModelBoundary.propose_tool(_Provider(raw),goal,state,hits)
    assert proposal.call.tool is ToolName.QUERY_TIMING
