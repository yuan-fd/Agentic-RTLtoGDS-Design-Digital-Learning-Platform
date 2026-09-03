"""Recover a terminal Runtime submission without emitting a duplicate run."""
from apps.l1_workbench.service import WorkbenchService
from openroad_platform_contracts.agent_control import SemanticToolCall, ToolName
from openroad_platform_contracts.l1_policy import TrustedPolicyIdentity
from openroad_platform_scheduler.l1_loop import L1DurableLoop


def test_recover_observes_existing_terminal_submission_without_resubmit(tmp_path) -> None:
    service = WorkbenchService(tmp_path)
    session = service.start("Run one bounded implementation flow.")
    session = service.answer(session.session_id, [{
        "question_id": "objective-1", "field": "objective", "value": "one audited run",
    }])
    goal = service._goal(session.trace_id, session.goal_id)
    state, _ = service._load(session.session_id)
    trusted = service.policy()
    identity = TrustedPolicyIdentity(trusted.policy_id, trusted.policy_version,
                                     trusted.issuer, trusted.provenance)
    call = SemanticToolCall("recover-call", goal.goal_id, state.state_id,
                            ToolName.RUN_FULL_FLOW, {}, "recovery-test")
    loop = L1DurableLoop(service.loop_store, service._bridge(goal), service.trace)
    plan = loop.plan_validate_execute(session.trace_id, goal, state, call, identity,
                                      planner_summary="submit then simulate controller loss")
    service._save(session.session_id, state, plan["plan_id"])
    service.runtime.execute_once(plan["run_id"])
    before = service.runtime.describe(plan["run_id"])
    assert before["run"]["status"] == "succeeded"
    service.recover(session.session_id)
    successor, _ = service._load(session.session_id)
    assert successor.diagnosis["runtime_run_id"] == plan["run_id"]
    assert successor.diagnosis["runtime_terminal_status"] == "succeeded"
    assert service.runtime.describe(plan["run_id"]) == before
    assert [event["kind"] for event in service.events(session.session_id)].count("state_transition") == 1
