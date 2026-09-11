from __future__ import annotations

import json
import platform
import sys
from pathlib import Path

import pytest

from openroad_platform_contracts import (
    AgentBudget, DesignGoal, DesignState, EvidencePointer, GoalPreference,
    PluginManifest, QoRConstraint, SemanticToolCall, TaskSpec, ToolName,
)
from openroad_platform_contracts.l1_policy import TrustedPolicyIdentity
from openroad_platform_execution import PluginRegistry
from openroad_platform_scheduler import RuntimeStore, WorkflowRuntime
from openroad_platform_scheduler.l1_loop import L1DurableLoop
from openroad_platform_scheduler.l1_loop_store import L1LoopStore
from openroad_platform_scheduler.l1_runtime_bridge import L1RuntimeBridge
from openroad_platform_scheduler.l1_semantic_policy import L1SemanticToolPolicy
from openroad_platform_scheduler.l1_trace_service import L1TraceService
from openroad_platform_scheduler.l1_trace_store import L1TraceStore


class _EDATaskFactory:
    capability = "eda.rtl_to_gds"

    @staticmethod
    def validate_task(task):
        task.validate()

    @staticmethod
    def reconfigure(task, _values):
        return task


class _KnowledgeFactory:
    capability = "knowledge.openroad.retrieve"

    @staticmethod
    def build(request):
        request.validate()
        return TaskSpec(
            request.task_id, request.project_id, request.design_id,
            plugin_id="knowledge-fixture",
            inputs={"query": request.query, "purpose": request.purpose},
            expected_artifacts=(
                "knowledge_retrieval", "knowledge_explanation",
                "knowledge_provenance",
            ),
            timeout_seconds=10, labels=dict(request.labels),
        )

    @staticmethod
    def validate_task(task):
        task.validate()
        if task.plugin_id != "knowledge-fixture":
            raise ValueError("wrong knowledge plugin")


def _goal():
    policy = EvidencePointer("artifact:policy", "d" * 64)
    return DesignGoal(
        "goal-1", "project-1", "design-1", "platform-1", "pdk-1",
        "toolchain-1", EvidencePointer("artifact:rtl", "a" * 64),
        GoalPreference.BALANCED, (QoRConstraint("wns", ">=", 0),),
        ("route",), ("density",), AgentBudget(1, 2, 60),
        allowed_tools=(ToolName.QUERY_OPENROAD_KNOWLEDGE,), labels={
            "l1_policy_id": "policy-1", "l1_policy_version": "v1",
            "l1_policy_issuer": "platform",
            "l1_policy_provenance": policy.ref,
            "l1_policy_provenance_sha256": policy.sha256,
        },
    )


def test_knowledge_tool_runs_policy_runtime_and_returns_artifact_citations(tmp_path):
    adapter = tmp_path / "knowledge_adapter.py"
    adapter.write_text('''
import argparse, json
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument("--request"); p.add_argument("--result"); a=p.parse_args()
root=Path(a.result).parent
values={
 "retrieval.json":{"method":"upstream-bm25","results":[{"citation_id":"ORAK-001","rank":1,"source_path":"src/drt/test/via_access_layer.ok","document_sha256":"a"*64,"chunk_sha256":"b"*64,"text":"[WARNING DRT-0349] has no via access."}]},
 "explanation.json":{"facts":[{"citation_id":"ORAK-001","quote":"no via access"}],"hypotheses":[],"counter_evidence":[],"unknowns":["Check exact run context."],"diagnostic_claim":False},
 "provenance.json":{"claim_scope":"retrieval-only"}}
for name,value in values.items(): (root/name).write_text(json.dumps(value))
Path(a.result).write_text(json.dumps({"schema_version":1,"status":"succeeded","exit_code":0,"started_at":"2026-09-05T00:00:00+00:00","ended_at":"2026-09-05T00:00:01+00:00","metrics":[],"artifacts":[{"kind":"knowledge_retrieval","path":"retrieval.json"},{"kind":"knowledge_explanation","path":"explanation.json"},{"kind":"knowledge_provenance","path":"provenance.json"}],"failure":None,"provenance":{}}))
''')
    manifest = PluginManifest(
        "knowledge-fixture", "1", (sys.executable, str(adapter)),
        ("knowledge.openroad.retrieve",), (platform.machine(),),
        {"type": "object"}, {"type": "object"},
        tuple({"kind": kind, "required": True} for kind in (
            "knowledge_retrieval", "knowledge_explanation",
            "knowledge_provenance")), 10,
    )
    runtime = WorkflowRuntime(
        RuntimeStore(tmp_path / "runtime.sqlite"), PluginRegistry([manifest]),
        workspace_root=tmp_path / "work")
    bridge = L1RuntimeBridge(
        runtime,
        TaskSpec("eda-base", "project-1", "design-1", plugin_id="unused",
                 inputs={}, timeout_seconds=10),
        _EDATaskFactory(), knowledge_factory=_KnowledgeFactory())
    trace = L1TraceService(L1TraceStore(tmp_path / "trace.sqlite"))
    goal = _goal(); trace.record_goal("trace-1", goal)
    state = DesignState("state-1", goal.goal_id, 0, "running", None, {},
                        AgentBudget(1, 2, 60), evidence=(goal.rtl_artifact,))
    call = SemanticToolCall(
        "call-1", goal.goal_id, state.state_id,
        ToolName.QUERY_OPENROAD_KNOWLEDGE,
        {"query": "Explain DRT-0349", "purpose": "error_explanation",
         "top_k": 3}, "planner")
    loop = L1DurableLoop(L1LoopStore(tmp_path / "loop.sqlite"), bridge, trace)
    plan = loop.plan_validate_execute(
        "trace-1", goal, state, call,
        TrustedPolicyIdentity("policy-1", "v1", "platform",
                              EvidencePointer("artifact:policy", "d" * 64)),
        planner_summary="Retrieve cited OpenROAD evidence.")
    receipt = plan["receipt"]
    assert receipt["status"] == "completed"
    assert receipt["result"]["diagnostic_claim"] is False
    assert receipt["result"]["citations"][0]["source_document"].endswith("via_access_layer.ok")
    assert receipt["result"]["citations"][0]["evidence"]["ref"].startswith("artifact:runtime-")
    assert state.remaining_budget.max_eda_runs == 1
    assert [event.kind.value for event in trace.store.read("trace-1")][-3:] == [
        "tool_called", "policy_decided", "tool_receipt"]


@pytest.mark.parametrize("arguments", [
    {"query": "DRT-0349", "url": "https://invalid"},
    {"query": "DRT-0349", "path": "/tmp/log"},
    {"query": "DRT-0349", "command": "make finish"},
])
def test_knowledge_tool_rejects_untyped_execution_or_location_fields(tmp_path, arguments):
    goal = _goal()
    state = DesignState("state-1", goal.goal_id, 0, "running", None, {},
                        AgentBudget(1, 2, 60))
    call = SemanticToolCall("call-1", goal.goal_id, state.state_id,
                            ToolName.QUERY_OPENROAD_KNOWLEDGE, arguments, "planner")
    with pytest.raises(ValueError):
        L1SemanticToolPolicy.validate(goal, state, call)
