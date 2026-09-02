"""Deterministically reduce Runtime observations into evidence-backed L1 state."""

from __future__ import annotations

from dataclasses import replace

from openroad_platform_contracts.agent_control import DesignState
from openroad_platform_contracts.l1_observation import RuntimeObservation


class L1StateReducer:
    @staticmethod
    def apply(state: DesignState, observation: RuntimeObservation, *, next_state_id: str) -> DesignState:
        state.validate()
        observation.validate()
        if state.status in {"failed", "stopped", "completed"}:
            raise ValueError("terminal DesignState cannot be advanced")
        next_status = "observed" if observation.terminal_status == "succeeded" else "failed"
        result = replace(
            state, state_id=next_state_id, parent_state_id=state.state_id,
            revision=state.revision + 1, status=next_status,
            completed_stage=observation.completed_stage,
            metrics=dict(observation.metrics), evidence=tuple(observation.evidence),
            diagnosis={"runtime_run_id": observation.run_id, "runtime_attempt_id": observation.attempt_id,
                       "runtime_terminal_status": observation.terminal_status},
        )
        result.validate()
        return result
