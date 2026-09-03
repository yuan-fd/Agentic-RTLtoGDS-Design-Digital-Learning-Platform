"""Thin, policy-gated handoff from an L1 terminal state to an external L2 plugin."""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from openroad_platform_contracts.agent_control import DesignGoal, DesignState
from openroad_platform_contracts.l2_optimization import OptimizationRequest, L2HandoffAuthorization
from openroad_platform_contracts.platform import PluginManifest, TaskSpec
from openroad_platform_contracts.l1_trace import TraceEventKind
from openroad_platform_contracts.product_surface import ProductRole, ProductSurface


class OptimizationHandoffService:
    """Authorize and correlate a TaskSpec; never implement an optimizer."""
    def __init__(self, surface: ProductSurface, task_builder: Callable[[OptimizationRequest, DesignGoal, DesignState], TaskSpec], *, trace_store: Any | None = None) -> None:
        self._surface, self._task_builder, self._trace_store = surface, task_builder, trace_store

    def task_for(self, request: OptimizationRequest, goal: DesignGoal, state: DesignState,
                 manifest: PluginManifest) -> TaskSpec:
        request.validate(); goal.validate(); state.validate(); manifest.validate()
        if request.goal_id != goal.goal_id or request.source_state_id != state.state_id or state.goal_id != goal.goal_id:
            raise ValueError("optimization request does not bind the finalized L1 goal/state")
        if state.status != "completed" or not state.evidence:
            raise ValueError("optimization handoff requires an evidence-backed terminal L1 state")
        return self._task_for_bound(request, goal, state, manifest)

    def task_for_authorized(self, request: OptimizationRequest, goal: DesignGoal, state: DesignState,
                            authorization: L2HandoffAuthorization, manifest: PluginManifest) -> TaskSpec:
        """Accept only the explicit audited L1→L2 escalation projection.

        This does *not* weaken :meth:`task_for`: arbitrary observed states are
        still rejected.  The authorizer is responsible for reading the durable
        trace and constructing this immutable receipt.
        """
        request.validate(); goal.validate(); state.validate(); authorization.validate(); manifest.validate()
        if state.status != "observed" or not state.evidence:
            raise ValueError("authorized L2 handoff requires an evidence-backed observed L1 state")
        if (authorization.l1_trace_id != request.l1_trace_id or authorization.goal_id != goal.goal_id
                or authorization.source_state_id != state.state_id or request.goal_id != goal.goal_id
                or request.source_state_id != state.state_id):
            raise ValueError("L2 authorization does not bind the finalized L1 goal/state/trace")
        self._verify_durable_authorization(authorization)
        return self._task_for_bound(request, goal, state, manifest, authorization=authorization)

    def _verify_durable_authorization(self, authorization: L2HandoffAuthorization) -> None:
        if self._trace_store is None:
            raise ValueError("authorized L2 handoff requires a durable trace verifier")
        events = self._trace_store.read(authorization.l1_trace_id)
        matching = [event for event in events if event.kind is TraceEventKind.L2_HANDOFF_AUTHORIZED
                    and event.facts.get("handoff_id") == authorization.authorization_id]
        if len(matching) != 1:
            raise ValueError("authorized L2 handoff requires one durable authorization receipt")
        event = matching[0]
        expected = {"l1_trace_id": authorization.l1_trace_id, "goal_id": authorization.goal_id,
                    "source_state_id": authorization.source_state_id,
                    "reflection_event_id": authorization.reflection_event_id,
                    "baseline_run_id": authorization.baseline_run_id,
                    "candidate_run_id": authorization.candidate_run_id}
        if event.goal_id != authorization.goal_id or any(event.facts.get(key) != value for key, value in expected.items()):
            raise ValueError("durable L2 authorization receipt binding mismatch")
        if tuple(event.evidence) != authorization.evidence:
            raise ValueError("durable L2 authorization receipt evidence mismatch")

    def _task_for_bound(self, request: OptimizationRequest, goal: DesignGoal, state: DesignState,
                        manifest: PluginManifest, authorization: L2HandoffAuthorization | None = None) -> TaskSpec:
        rule = self._surface.rule_for(ProductRole.L2_OPTIMIZATION)
        self._surface.authorize(ProductRole.L2_OPTIMIZATION, manifest)
        if (request.plugin_id, request.capability) != (rule.plugin_id, rule.capability):
            raise PermissionError("optimization request does not match the approved product capability")
        if manifest.plugin_id != request.plugin_id or request.capability not in manifest.capabilities:
            raise PermissionError("optimization request plugin/capability is not admitted")
        task = self._task_builder(request, goal, state)
        if not isinstance(task, TaskSpec):
            raise TypeError("external L2 task builder must return TaskSpec")
        task.validate()
        if task.plugin_id != request.plugin_id or task.project_id != goal.project_id or task.design_id != goal.design_id:
            raise ValueError("external L2 TaskSpec does not bind the approved Goal identity")
        labels = {**task.labels, "l1_trace_id": request.l1_trace_id,
                                     "l1_goal_id": goal.goal_id, "l1_state_id": state.state_id,
                                     "l2_request_id": request.request_id,
                                     "l2_protocol_evidence": request.protocol_evidence.ref,
                                     "l2_protocol_sha256": request.protocol_evidence.sha256}
        if authorization:
            labels.update({"l2_authorization_id": authorization.authorization_id,
                           "l2_reflection_event_id": authorization.reflection_event_id,
                           "l2_baseline_run_id": authorization.baseline_run_id,
                           "l2_candidate_run_id": authorization.candidate_run_id})
        return replace(task, labels=labels)

    def submit(self, runtime: Any, request: OptimizationRequest, goal: DesignGoal,
               state: DesignState, manifest: PluginManifest) -> Any:
        task = self.task_for(request, goal, state, manifest)
        return runtime.submit(task, capability=request.capability)
