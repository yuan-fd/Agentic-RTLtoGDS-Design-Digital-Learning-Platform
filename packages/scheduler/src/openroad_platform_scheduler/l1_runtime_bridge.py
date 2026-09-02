"""Thin Runtime-only backing for L1's fixed semantic tool surface.

This replaces the historical in-process L1 ORFS state cache.  It never starts
EDA itself and never interprets a model string as a command.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from typing import Any, Mapping

from openroad_platform_contracts.agent_control import DesignGoal, DesignState, SemanticToolCall, ToolName, ToolReceipt
from openroad_platform_contracts.l1_observation import RuntimeObservation
from openroad_platform_contracts.learning import EvidencePointer
from openroad_platform_contracts.platform import TaskSpec
from openroad_platform_contracts.task_factory import RTLToGDSFactory
from .l1_semantic_policy import L1SemanticToolPolicy
from .l1_state_reducer import L1StateReducer
from .l1_trace_service import L1TraceService


def _evidence(ref: str, value: object) -> EvidencePointer:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return EvidencePointer(ref, hashlib.sha256(raw).hexdigest())


class L1RuntimeBridge:
    """Translate typed calls to Runtime facts and immutable capability tasks."""
    def __init__(self, runtime: Any, base_task: TaskSpec, factory: RTLToGDSFactory) -> None:
        base_task.validate(); factory.validate_task(base_task)
        self._runtime, self._base_task, self._factory = runtime, base_task, factory

    @staticmethod
    def _binding(goal: DesignGoal, state: DesignState, call: SemanticToolCall) -> None:
        L1SemanticToolPolicy.validate(goal, state, call)

    @staticmethod
    def supported_tools() -> frozenset[ToolName]:
        return frozenset({ToolName.GET_DESIGN_SUMMARY, ToolName.QUERY_TIMING, ToolName.QUERY_CONGESTION,
                          ToolName.QUERY_DRC, ToolName.QUERY_POWER, ToolName.QUERY_STAGE_METRICS,
                          ToolName.QUERY_ARTIFACT_EXCERPT, ToolName.SET_FLOW_PARAMS, ToolName.RUN_STAGE,
                          ToolName.RUN_FULL_FLOW, ToolName.COMPARE_RUNS, ToolName.STOP_OR_ESCALATE})

    def submit(self, goal: DesignGoal, state: DesignState, call: SemanticToolCall) -> ToolReceipt:
        self._binding(goal, state, call)
        if call.tool not in {ToolName.RUN_STAGE, ToolName.RUN_FULL_FLOW}:
            raise ValueError("submit only supports run_stage or run_full_flow")
        parameters = dict(self._base_task.parameters)
        patch = call.arguments.get("parameter_patch", {})
        if patch:
            if not isinstance(patch, Mapping):
                raise ValueError("parameter_patch must be a typed mapping")
            parameters = dict(self._factory.reconfigure(self._base_task, patch).parameters)
        if call.tool is ToolName.RUN_STAGE:
            stage = call.arguments.get("stage")
            if stage not in goal.allowed_stages:
                raise ValueError("stage is outside the DesignGoal policy")
            parameters["target_stage"] = stage
        task = dataclasses.replace(self._base_task, task_id=f"l1-{call.call_id}", parameters=parameters,
                                   labels={**self._base_task.labels, "l1_goal_id": goal.goal_id, "l1_call_id": call.call_id})
        task.validate(); self._factory.validate_task(task)
        run = self._runtime.submit(task, capability=self._factory.capability)
        run_id = getattr(run, "run_id", None)
        if not isinstance(run_id, str) or not run_id:
            raise RuntimeError("Runtime submit returned no run_id")
        return ToolReceipt(call.call_id, goal.goal_id, state.state_id, call.tool, "accepted",
                           {"run_id": run_id, "capability": self._factory.capability}, (), None)

    def execute(self, goal: DesignGoal, state: DesignState, call: SemanticToolCall) -> ToolReceipt:
        """Dispatch only the tutorial's 12 typed tools; no generic executor exists."""
        if call.tool in {ToolName.RUN_STAGE, ToolName.RUN_FULL_FLOW}:
            return self.submit(goal, state, call)
        if call.tool is ToolName.SET_FLOW_PARAMS:
            return self.set_flow_params(goal, state, call)
        if call.tool is ToolName.STOP_OR_ESCALATE:
            return self.stop_or_escalate(goal, state, call)
        if call.tool is ToolName.GET_DESIGN_SUMMARY:
            return self.design_summary(goal, state, call)
        return self.query(goal, state, call)

    def set_flow_params(self, goal: DesignGoal, state: DesignState, call: SemanticToolCall) -> ToolReceipt:
        self._binding(goal, state, call)
        values = call.arguments.get("values")
        if call.tool is not ToolName.SET_FLOW_PARAMS or not isinstance(values, Mapping) or not values:
            raise ValueError("set_flow_params requires a non-empty typed values mapping")
        if set(values) - set(goal.allowed_parameters):
            raise ValueError("parameter patch is outside the DesignGoal policy")
        task = self._factory.reconfigure(self._base_task, values)
        pointer = _evidence(f"task-spec:{task.task_id}", task.to_dict())
        return ToolReceipt(call.call_id, goal.goal_id, state.state_id, call.tool, "completed",
                           {"parameter_patch": dict(values), "task_spec_sha256": pointer.sha256}, (pointer,))

    def stop_or_escalate(self, goal: DesignGoal, state: DesignState, call: SemanticToolCall) -> ToolReceipt:
        self._binding(goal, state, call)
        run_id = call.arguments.get("run_id")
        if call.tool is not ToolName.STOP_OR_ESCALATE or not isinstance(run_id, str) or not run_id:
            raise ValueError("stop_or_escalate requires a Runtime run_id")
        view = self._runtime.describe(run_id)
        labels = view.get("run", {}).get("task_spec", {}).get("labels", {})
        if labels.get("l1_goal_id") != goal.goal_id:
            raise ValueError("Runtime run is not owned by this DesignGoal")
        request_cancel = getattr(self._runtime, "request_cancel", None)
        if not callable(request_cancel):
            raise ValueError("Runtime does not expose controlled cancellation")
        request_cancel(run_id)
        return ToolReceipt(call.call_id, goal.goal_id, state.state_id, call.tool, "accepted",
                           {"run_id": run_id, "action": "cancel_requested"}, (), None)

    def design_summary(self, goal: DesignGoal, state: DesignState, call: SemanticToolCall) -> ToolReceipt:
        self._binding(goal, state, call)
        if call.tool is not ToolName.GET_DESIGN_SUMMARY:
            raise ValueError("design_summary requires get_design_summary")
        summary = {"project_id": goal.project_id, "design_id": goal.design_id, "platform": goal.platform,
                   "pdk_id": goal.pdk_id, "toolchain_id": goal.toolchain_id,
                   "allowed_stages": list(goal.allowed_stages), "rtl_artifact": goal.rtl_artifact.ref}
        return ToolReceipt(call.call_id, goal.goal_id, state.state_id, call.tool, "completed", summary,
                           (goal.rtl_artifact,))

    def query(self, goal: DesignGoal, state: DesignState, call: SemanticToolCall) -> ToolReceipt:
        self._binding(goal, state, call)
        if call.tool not in {ToolName.GET_DESIGN_SUMMARY, ToolName.QUERY_TIMING, ToolName.QUERY_CONGESTION,
                             ToolName.QUERY_DRC, ToolName.QUERY_POWER, ToolName.QUERY_STAGE_METRICS,
                             ToolName.QUERY_ARTIFACT_EXCERPT, ToolName.COMPARE_RUNS}:
            raise ValueError("call is not a Runtime read tool")
        run_ids = [value for key, value in call.arguments.items() if key.endswith("run_id") and isinstance(value, str)]
        if not run_ids:
            raise ValueError("Runtime read tool requires a typed run identifier")
        views = {run_id: self._runtime.describe(run_id) for run_id in run_ids}
        for view in views.values():
            self._require_owned_run(goal, view)
        result: dict[str, Any] = {"run_ids": run_ids, "view": self._bounded(views)}
        if call.tool is ToolName.QUERY_ARTIFACT_EXCERPT:
            read = getattr(self._runtime, "read_artifact_excerpt", None)
            if not callable(read): raise ValueError("Runtime does not expose controlled artifact reads")
            result = {"run_id": run_ids[0], **read(run_ids[0], call.arguments["artifact_id"],
                                                    offset=call.arguments.get("offset", 0), max_bytes=call.arguments["max_bytes"])}
        elif call.tool is ToolName.COMPARE_RUNS:
            metric_names = call.arguments["metrics"]
            summary = {run_id: self._metrics(view) for run_id, view in views.items()}
            result = {"left_run_id": run_ids[0], "right_run_id": run_ids[1], "metrics": {name: {run_id: summary[run_id].get(name) for run_id in run_ids} for name in metric_names}}
        return ToolReceipt(call.call_id, goal.goal_id, state.state_id, call.tool, "completed",
                           result,
                           tuple(_evidence(f"runtime:{run_id}", view) for run_id, view in views.items()))

    def observation(self, run_id: str) -> RuntimeObservation:
        view = self._runtime.describe(run_id); run = view["run"]
        if run.get("status") not in {"succeeded", "failed", "cancelled", "timed_out", "lost"}:
            raise ValueError("Runtime observation requires a terminal run")
        candidates = [(stage, attempt) for stage in view.get("stages", ()) for attempt in stage.get("attempts", ())
                      if (run["status"] == "succeeded" and stage.get("successful_attempt_id") == attempt.get("attempt_id"))
                      or (run["status"] != "succeeded" and attempt.get("status") in {run["status"], run.get("terminal_reason")})]
        if len(candidates) != 1:
            raise ValueError("Runtime run has no attempt observation")
        stage_view, attempt = candidates[0]; metrics = {item["name"]: float(item["value"]) for item in attempt.get("metrics", ())
                                            if isinstance(item.get("value"), (int, float)) and not isinstance(item.get("value"), bool)}
        evidence = tuple(_evidence(f"artifact:runtime-{item['artifact_id']}", item) for item in attempt.get("artifacts", ()))
        if not evidence:
            evidence = (_evidence(f"runtime:{run_id}", view),)
        return RuntimeObservation(run_id, attempt["attempt_id"], stage_view.get("stage_key"), run["status"], metrics, evidence)

    def reduce_and_trace(self, trace: L1TraceService, trace_id: str, state: DesignState,
                         *, run_id: str, next_state_id: str) -> DesignState:
        """The only S3 handoff from Runtime facts into the S2 state authority."""
        observation = self.observation(run_id)
        self._require_owned_run_from_id(state.goal_id, run_id)
        successor = L1StateReducer.apply(state, observation, next_state_id=next_state_id)
        trace.record_observation(trace_id, state, successor, observation)
        return successor

    @staticmethod
    def _bounded(value: Mapping[str, Any]) -> dict[str, Any]:
        return {key: value[key] for key in sorted(value)[:8]}

    @staticmethod
    def _metrics(view: Mapping[str, Any]) -> dict[str, float]:
        return {item["name"]: float(item["value"]) for stage in view.get("stages", ()) for attempt in stage.get("attempts", ()) for item in attempt.get("metrics", ()) if isinstance(item.get("value"), (int, float)) and not isinstance(item.get("value"), bool)}

    @staticmethod
    def _require_owned_run(goal: DesignGoal, view: Mapping[str, Any]) -> None:
        if view.get("run", {}).get("task_spec", {}).get("labels", {}).get("l1_goal_id") != goal.goal_id:
            raise ValueError("Runtime run is not owned by this DesignGoal")

    def _require_owned_run_from_id(self, goal_id: str, run_id: str) -> None:
        view = self._runtime.describe(run_id)
        if view.get("run", {}).get("task_spec", {}).get("labels", {}).get("l1_goal_id") != goal_id:
            raise ValueError("Runtime run is not owned by this DesignGoal")
