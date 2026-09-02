"""S4 durable Plan -> Validate -> Execute -> Observe orchestration."""
from __future__ import annotations
from uuid import uuid4
from openroad_platform_contracts.agent_control import DesignGoal, DesignState, SemanticToolCall
from openroad_platform_contracts.l1_policy import TrustedPolicyIdentity
from .l1_loop_store import L1LoopStore
from .l1_runtime_bridge import L1RuntimeBridge
from .l1_semantic_policy import L1SemanticToolPolicy
from .l1_trace_service import L1TraceService

class L1DurableLoop:
    def __init__(self, store: L1LoopStore, bridge: L1RuntimeBridge, trace: L1TraceService) -> None:
        self.store, self.bridge, self.trace = store, bridge, trace
    def plan_validate_execute(self, trace_id: str, goal: DesignGoal, state: DesignState, call: SemanticToolCall, policy: TrustedPolicyIdentity, *, planner_summary: str) -> dict:
        L1SemanticToolPolicy.validate(goal, state, call)
        plan_id = f"plan-{uuid4().hex}"; self.store.propose(plan_id, trace_id, goal.goal_id, state.state_id, call.to_dict())
        self.trace.record_call(trace_id, state, call, planner_summary=planner_summary)
        self.trace.record_policy(trace_id, goal, state, call, policy, verdict="allow", summary="typed policy accepted call")
        receipt = self.bridge.execute(goal, state, call); self.trace.record_receipt(trace_id, state, receipt)
        self.store.record_receipt(plan_id, receipt.to_dict())
        return self.store.get(plan_id)
    def observe(self, trace_id: str, state: DesignState, plan_id: str, *, next_state_id: str) -> DesignState:
        plan = self.store.get(plan_id)
        if plan["status"] != "submitted" or not plan["run_id"]: raise ValueError("plan has no Runtime submission to observe")
        if plan["trace_id"] != trace_id or plan["goal_id"] != state.goal_id or plan["state_id"] != state.state_id: raise ValueError("plan does not bind current trace/goal/state")
        return self.bridge.reduce_and_trace(self.trace, trace_id, state, run_id=plan["run_id"], next_state_id=next_state_id)
