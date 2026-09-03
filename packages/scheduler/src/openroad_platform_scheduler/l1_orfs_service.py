"""Runtime binding for L1 semantic tools on an already verified ORFS task.

The service accepts a task whose RTL artifact was admitted by the RTL frontend.
It creates only validated ``TaskSpec`` objects and submits them through the
existing Runtime authority.  It never executes a command, accepts a path, or
lets a policy manufacture an adapter invocation.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from typing import Any, Mapping

from openroad_platform_contracts import (
    AgentBudget, DesignGoal, DesignState, EvidencePointer, SemanticToolCall,
    RTLToGDSFactory, TaskSpec, ToolName, ToolReceipt,
)

from .semantic_tools import SemanticToolRegistry, ToolDefinition


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class L1ORFSToolService:
    """Bind semantic tools to a protected ORFS Runtime submission API."""

    def __init__(self, runtime: Any, base_task: TaskSpec,
                 rtl_to_gds_factory: RTLToGDSFactory, *,
                 capability: str | None = None) -> None:
        base_task.validate()
        rtl_to_gds_factory.validate_task(base_task)
        if capability is not None and capability != rtl_to_gds_factory.capability:
            raise ValueError("L1 capability must match the selected task factory")
        self.runtime = runtime
        self.base_task = base_task
        self.rtl_to_gds_factory = rtl_to_gds_factory
        self.capability = rtl_to_gds_factory.capability
        self._experiments: dict[str, TaskSpec] = {}
        self._states: dict[str, DesignState] = {}
        self.registry = SemanticToolRegistry()
        for tool, mutates, handler in (
            (ToolName.CREATE_EXPERIMENT, True, self._create_experiment),
            (ToolName.SET_FLOW_PARAMS, True, self._set_flow_params),
            (ToolName.RUN_STAGE, True, self._run_stage),
            (ToolName.QUERY_TIMING, False, self._query),
            (ToolName.QUERY_CONGESTION, False, self._query),
            (ToolName.QUERY_DRC, False, self._query),
            (ToolName.QUERY_POWER, False, self._query),
            (ToolName.QUERY_ARTIFACT_EXCERPT, False, self._query),
            (ToolName.COMPARE_RUNS, False, self._compare_runs),
            (ToolName.PROPOSE_SEARCH_POLICY, False, self._policy_receipt),
            (ToolName.STOP_OR_ESCALATE, True, self._stop),
        ):
            self.registry.register(ToolDefinition(tool, mutates, handler))

    def execute(self, goal: DesignGoal, state: DesignState,
                call: SemanticToolCall) -> ToolReceipt:
        self._states[state.state_id] = state
        return self.registry.execute(goal, state, call)

    def state(self, state_id: str) -> DesignState:
        try:
            return self._states[state_id]
        except KeyError as exc:
            raise KeyError(f"unknown L1 DesignState: {state_id}") from exc

    def observe(self, state: DesignState, *, run_id: str, metrics: Mapping[str, float],
                evidence: EvidencePointer, status: str = "observed",
                completed_stage: str | None = None,
                diagnosis: Mapping[str, Any] | None = None) -> DesignState:
        """Admit a canonical evaluator result as the next immutable state.

        The caller is the trusted Runtime/evaluator bridge, not the LLM.  It
        must provide a content-addressed result pointer; raw report parsing
        remains in the common evaluator and EDAIR layers.
        """
        state.validate(); evidence.validate()
        if status not in {"observed", "failed", "completed"}:
            raise ValueError("observe status is unsupported")
        if not run_id or not isinstance(run_id, str):
            raise ValueError("observe requires a Runtime run id")
        successor = self._successor(
            state, f"observe-{_digest({'state': state.state_id, 'run': run_id, 'evidence': evidence.sha256})[:24]}",
            status=status, metrics={str(name): float(value) for name, value in metrics.items()},
            evidence=(evidence,), completed_stage=completed_stage,
            diagnosis=dict(diagnosis or {}), decrement_run=False,
        )
        self._states[successor.state_id] = successor
        return successor

    def _create_experiment(self, goal: DesignGoal, state: DesignState,
                           call: SemanticToolCall) -> ToolReceipt:
        experiment_id = f"experiment-{_digest({'goal': goal.goal_id, 'call': call.call_id})[:24]}"
        seed = int(call.arguments.get("or_seed", self.base_task.parameters.get("or_seed", 1)))
        task = dataclasses.replace(
            self.base_task, task_id=f"l1-{_digest({'experiment': experiment_id})[:24]}",
            parameters={**self.base_task.parameters, "or_seed": seed},
            labels={**self.base_task.labels, "l1_goal_id": goal.goal_id,
                    "l1_experiment_id": experiment_id,
                    "l1_experiment_name": str(call.arguments["name"])},
        )
        task.validate(); self._experiments[experiment_id] = task
        next_state = self._successor(state, call.call_id, status="running",
                                     evidence=(goal.rtl_artifact,), decrement_run=False)
        return self._completed(goal, state, call, {"experiment_id": experiment_id,
                               "task_id": task.task_id}, (goal.rtl_artifact,), next_state)

    def _set_flow_params(self, goal: DesignGoal, state: DesignState,
                         call: SemanticToolCall) -> ToolReceipt:
        experiment_id = str(call.arguments["experiment_id"])
        task = self._experiment(experiment_id)
        values = dict(call.arguments["values"])
        task = self.rtl_to_gds_factory.reconfigure(task, values)
        self._experiments[experiment_id] = task
        next_state = self._successor(state, call.call_id, status="running",
                                     evidence=state.evidence or (goal.rtl_artifact,), decrement_run=False)
        return self._completed(goal, state, call,
                               {"experiment_id": experiment_id, "effective_parameters": values},
                               next_state.evidence, next_state)

    def _run_stage(self, goal: DesignGoal, state: DesignState,
                   call: SemanticToolCall) -> ToolReceipt:
        experiment_id = str(call.arguments["experiment_id"])
        task = self._experiment(experiment_id)
        task = dataclasses.replace(task, task_id=f"l1-run-{_digest({'call': call.call_id})[:24]}",
                                   parameters={**task.parameters, "target_stage": call.arguments["stage"]})
        task.validate()
        run = self.runtime.submit(task, capability=self.capability)
        run_id = str(getattr(run, "run_id", ""))
        if not run_id:
            raise RuntimeError("Runtime submit returned no run_id")
        self._experiments[experiment_id] = task
        next_state = self._successor(state, call.call_id, status="running",
                                     evidence=state.evidence or (goal.rtl_artifact,), decrement_run=True)
        # A submitted run has no final report yet, so this is deliberately
        # "accepted" rather than a false claim of completed evaluation.
        return ToolReceipt(call.call_id, goal.goal_id, state.state_id, call.tool, "accepted",
                           {"experiment_id": experiment_id, "run_id": run_id,
                            "target_stage": call.arguments["stage"]}, (),
                           next_state.state_id)

    def _query(self, goal: DesignGoal, state: DesignState,
               call: SemanticToolCall) -> ToolReceipt:
        view = self.runtime.describe(str(call.arguments["run_id"]))
        evidence = self._view_evidence(call.arguments["run_id"], view)
        return ToolReceipt(call.call_id, goal.goal_id, state.state_id, call.tool, "completed",
                           {"run_id": call.arguments["run_id"], "query": call.tool.value,
                            "view": self._bounded_view(view, call.arguments.get("limit", 32))},
                           (evidence,))

    def _compare_runs(self, goal: DesignGoal, state: DesignState,
                      call: SemanticToolCall) -> ToolReceipt:
        left = self.runtime.describe(str(call.arguments["left_run_id"]))
        right = self.runtime.describe(str(call.arguments["right_run_id"]))
        metrics = tuple(call.arguments.get("metrics") or ())
        return ToolReceipt(call.call_id, goal.goal_id, state.state_id, call.tool, "completed",
                           {"left_run_id": call.arguments["left_run_id"],
                            "right_run_id": call.arguments["right_run_id"],
                            "metrics": list(metrics), "comparison": "runtime views retained by reference"},
                           (self._view_evidence(call.arguments["left_run_id"], left),
                            self._view_evidence(call.arguments["right_run_id"], right)))

    def _policy_receipt(self, goal: DesignGoal, state: DesignState,
                        call: SemanticToolCall) -> ToolReceipt:
        evidence = call.evidence or state.evidence
        return ToolReceipt(call.call_id, goal.goal_id, state.state_id, call.tool, "completed",
                           {"mode": call.arguments["mode"],
                            "parameter_subset": list(call.arguments["parameter_subset"]),
                            "execution_allowed": False}, evidence)

    def _stop(self, goal: DesignGoal, state: DesignState,
              call: SemanticToolCall) -> ToolReceipt:
        next_state = self._successor(state, call.call_id, status="stopped",
                                     evidence=state.evidence or (goal.rtl_artifact,), decrement_run=False)
        return self._completed(goal, state, call,
                               {"reason": call.arguments["reason"],
                                "target_level": call.arguments.get("target_level")},
                               next_state.evidence, next_state)

    def _successor(self, state: DesignState, call_id: str, *, status: str,
                   evidence: tuple[EvidencePointer, ...], decrement_run: bool,
                   metrics: Mapping[str, float] | None = None,
                   completed_stage: str | None = None,
                   diagnosis: Mapping[str, Any] | None = None) -> DesignState:
        budget = state.remaining_budget
        if decrement_run:
            if budget.max_eda_runs < 1:
                raise ValueError("DesignGoal EDA-run budget is exhausted")
            budget = dataclasses.replace(budget, max_eda_runs=budget.max_eda_runs - 1)
        successor = dataclasses.replace(
            state, state_id=f"state-{_digest({'parent': state.state_id, 'call': call_id})[:24]}",
            parent_state_id=state.state_id, revision=state.revision + 1, status=status,
            metrics=dict(metrics if metrics is not None else state.metrics),
            evidence=tuple(evidence), remaining_budget=budget,
            completed_stage=completed_stage if completed_stage is not None else state.completed_stage,
            diagnosis=dict(diagnosis if diagnosis is not None else state.diagnosis),
        )
        successor.validate(); self._states[successor.state_id] = successor
        return successor

    @staticmethod
    def _completed(goal: DesignGoal, state: DesignState, call: SemanticToolCall,
                   result: dict[str, Any], evidence: tuple[EvidencePointer, ...],
                   successor: DesignState) -> ToolReceipt:
        return ToolReceipt(call.call_id, goal.goal_id, state.state_id, call.tool, "completed",
                           result, evidence, successor.state_id)

    def _experiment(self, experiment_id: str) -> TaskSpec:
        try:
            return self._experiments[experiment_id]
        except KeyError as exc:
            raise ValueError("semantic tool references unknown experiment") from exc

    @staticmethod
    def _view_evidence(run_id: Any, view: Mapping[str, Any]) -> EvidencePointer:
        raw = json.dumps(dict(view), sort_keys=True, separators=(",", ":"), default=str).encode()
        return EvidencePointer(ref=f"run:{run_id}", sha256=hashlib.sha256(raw).hexdigest())

    @staticmethod
    def _bounded_view(view: Mapping[str, Any], limit: Any) -> dict[str, Any]:
        maximum = int(limit or 32)
        # The detailed Runtime view remains available under its hash.  The LLM
        # receives only a bounded top-level projection through this tool.
        keys = sorted(str(key) for key in view)[:maximum]
        return {key: view[key] for key in keys}
