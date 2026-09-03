"""S4 durable Plan -> Validate -> Execute -> Observe orchestration."""
from __future__ import annotations
from uuid import uuid4
from dataclasses import replace
from openroad_platform_contracts.agent_control import DesignGoal, DesignState, SemanticToolCall
from openroad_platform_contracts.l1_policy import TrustedPolicyIdentity
from .l1_loop_store import L1LoopStore
from .l1_runtime_bridge import L1RuntimeBridge
from .l1_trace_service import L1TraceService
from .l1_tool_registry import L1RuntimeToolRegistry

class L1DurableLoop:
    def __init__(self, store: L1LoopStore, bridge: L1RuntimeBridge, trace: L1TraceService) -> None:
        self.store, self.bridge, self.trace = store, bridge, trace
        self.tools = L1RuntimeToolRegistry(bridge)
    def plan_validate_execute(self, trace_id: str, goal: DesignGoal, state: DesignState, call: SemanticToolCall, policy: TrustedPolicyIdentity, *, planner_summary: str) -> dict:
        self.tools.validate(goal, state, call)
        if call.tool.value in {"run_stage", "run_full_flow"} and state.remaining_budget.max_eda_runs < 1:
            raise ValueError("DesignGoal EDA-run budget is exhausted")
        plan_id = f"plan-{uuid4().hex}"
        self.store.propose(plan_id, trace_id, goal.goal_id, state.state_id, call.to_dict())
        if call.tool.value == "set_flow_params":
            self.store.save_proposal(f"proposal-{call.call_id}", trace_id, goal.goal_id, state.state_id, dict(call.arguments["values"]))
        proposal_id = call.arguments.get("proposal_id")
        if proposal_id:
            patch = self.store.reserve_proposal(proposal_id, trace_id, goal.goal_id, state.state_id, plan_id)
            call = replace(call, arguments={**call.arguments, "parameter_patch": patch})
            self.tools.validate(goal, state, call)
        # The persisted call is exactly the call that will reach the bridge.
        self.store.prepare_execution(plan_id, call.to_dict())
        try:
            self.trace.record_call(trace_id, state, call, planner_summary=planner_summary)
            self.trace.record_policy(trace_id, goal, state, call, policy, verdict="allow", summary="typed policy accepted call")
        except Exception:
            self.store.release_reservation(plan_id)
            raise
        try:
            receipt = self.tools.execute(goal, state, call)
        except Exception:
            # No accepted Runtime receipt exists, so a new plan may safely reuse it.
            self.store.release_reservation(plan_id)
            raise
        # Receipt trace precedes proposal consumption.  If committing the local
        # receipt fails, its durable trace event lets recover_submission finish
        # the reservation without resubmitting Runtime work.
        self.trace.record_receipt(trace_id, state, receipt)
        self.store.record_receipt(plan_id, receipt.to_dict())
        return self.store.get(plan_id)
    def observe(self, trace_id: str, state: DesignState, plan_id: str, *, next_state_id: str) -> DesignState:
        plan = self.store.get(plan_id)
        if plan["status"] != "submitted" or not plan["run_id"]: raise ValueError("plan has no Runtime submission to observe")
        if plan["trace_id"] != trace_id or plan["goal_id"] != state.goal_id or plan["state_id"] != state.state_id: raise ValueError("plan does not bind current trace/goal/state")
        successor = self.bridge.reduce_and_trace(
            self.trace, trace_id, state, run_id=plan["run_id"], next_state_id=next_state_id,
            consume_eda_run=plan["call"]["tool"] in {"run_stage", "run_full_flow"},
        )
        if plan["call"]["tool"] == "stop_or_escalate":
            self.trace.record_stopped(trace_id, successor, run_id=plan["run_id"], reason=plan["call"]["arguments"]["reason"])
        return successor

    def recover_submission(self, trace_id: str, plan_id: str) -> dict:
        """Finish a receipt commit after a local SQLite interruption, never rerun."""
        plan = self.store.get(plan_id)
        if plan["trace_id"] != trace_id or plan["status"] != "prepared":
            raise ValueError("plan is not a recoverable prepared plan")
        call_id = plan["call"]["call_id"]
        receipts = [event for event in self.trace.store.read(trace_id)
                    if event.kind.value == "tool_receipt" and event.facts.get("call_id") == call_id]
        if len(receipts) != 1:
            raise ValueError("durable receipt trace is required for recovery")
        event = receipts[0]
        receipt = {"call_id": call_id, "goal_id": plan["goal_id"], "state_id": plan["state_id"],
                   "tool": plan["call"]["tool"], "status": event.facts["status"],
                   "result": event.facts["result"], "evidence": [item.to_dict() for item in event.evidence]}
        self.store.record_receipt(plan_id, receipt)
        return self.store.get(plan_id)
