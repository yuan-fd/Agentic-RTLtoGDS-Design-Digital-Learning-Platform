"""Deterministically reduce Runtime observations into evidence-backed L1 state."""

from __future__ import annotations

from dataclasses import replace

from openroad_platform_contracts.agent_control import AgentBudget, DesignState
from openroad_platform_contracts.l1_observation import RuntimeObservation


class L1StateReducer:
    @staticmethod
    def apply(state: DesignState, observation: RuntimeObservation, *, next_state_id: str,
              consume_eda_run: bool = False) -> DesignState:
        state.validate()
        observation.validate()
        if state.status in {"failed", "stopped", "completed"}:
            raise ValueError("terminal DesignState cannot be advanced")
        next_status = ("observed" if observation.terminal_status == "succeeded"
                       else "stopped" if observation.terminal_status == "cancelled"
                       else "failed")
        if consume_eda_run and state.remaining_budget.max_eda_runs < 1:
            raise ValueError("Runtime observation exceeds the finalized EDA budget")
        budget = (AgentBudget(state.remaining_budget.max_eda_runs - 1,
                              state.remaining_budget.max_llm_calls,
                              state.remaining_budget.max_wall_clock_seconds,
                              state.remaining_budget.max_parallel)
                  if consume_eda_run else state.remaining_budget)
        result = replace(
            state, state_id=next_state_id, parent_state_id=state.state_id,
            revision=state.revision + 1, status=next_status,
            completed_stage=observation.completed_stage,
            metrics=dict(observation.metrics), evidence=tuple(observation.evidence),
            remaining_budget=budget,
            diagnosis={"runtime_run_id": observation.run_id, "runtime_attempt_id": observation.attempt_id,
                       "runtime_terminal_status": observation.terminal_status},
        )
        result.validate()
        return result
