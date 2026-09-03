"""Thin, policy-gated handoff from an L1 terminal state to an external L2 plugin."""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from openroad_platform_contracts.agent_control import DesignGoal, DesignState
from openroad_platform_contracts.l2_optimization import OptimizationRequest
from openroad_platform_contracts.platform import PluginManifest, TaskSpec
from openroad_platform_contracts.product_surface import ProductRole, ProductSurface


class OptimizationHandoffService:
    """Authorize and correlate a TaskSpec; never implement an optimizer."""
    def __init__(self, surface: ProductSurface, task_builder: Callable[[OptimizationRequest, DesignGoal, DesignState], TaskSpec]) -> None:
        self._surface, self._task_builder = surface, task_builder

    def task_for(self, request: OptimizationRequest, goal: DesignGoal, state: DesignState,
                 manifest: PluginManifest) -> TaskSpec:
        request.validate(); goal.validate(); state.validate(); manifest.validate()
        if request.goal_id != goal.goal_id or request.source_state_id != state.state_id or state.goal_id != goal.goal_id:
            raise ValueError("optimization request does not bind the finalized L1 goal/state")
        if state.status not in {"observed", "completed"} or not state.evidence:
            raise ValueError("optimization handoff requires an evidence-backed terminal L1 state")
        self._surface.authorize(ProductRole.L2_OPTIMIZATION, manifest)
        if manifest.plugin_id != request.plugin_id or request.capability not in manifest.capabilities:
            raise PermissionError("optimization request plugin/capability is not admitted")
        task = self._task_builder(request, goal, state)
        if not isinstance(task, TaskSpec):
            raise TypeError("external L2 task builder must return TaskSpec")
        task.validate()
        if task.plugin_id != request.plugin_id or task.project_id != goal.project_id or task.design_id != goal.design_id:
            raise ValueError("external L2 TaskSpec does not bind the approved Goal identity")
        return replace(task, labels={**task.labels, "l1_trace_id": request.l1_trace_id,
                                     "l1_goal_id": goal.goal_id, "l1_state_id": state.state_id,
                                     "l2_request_id": request.request_id,
                                     "l2_protocol_evidence": request.protocol_evidence.ref,
                                     "l2_protocol_sha256": request.protocol_evidence.sha256})

    def submit(self, runtime: Any, request: OptimizationRequest, goal: DesignGoal,
               state: DesignState, manifest: PluginManifest) -> Any:
        task = self.task_for(request, goal, state, manifest)
        return runtime.submit(task, capability=request.capability)
