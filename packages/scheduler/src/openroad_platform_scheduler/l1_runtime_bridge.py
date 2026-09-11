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
from openroad_platform_contracts.task_factory import KnowledgeQueryRequest, KnowledgeTaskFactory, RTLToGDSFactory
from .l1_semantic_policy import L1SemanticToolPolicy
from .l1_state_reducer import L1StateReducer
from .l1_trace_service import L1TraceService


def _evidence(ref: str, value: object) -> EvidencePointer:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return EvidencePointer(ref, hashlib.sha256(raw).hexdigest())


class L1RuntimeBridge:
    """Translate typed calls to Runtime facts and immutable capability tasks."""
    def __init__(self, runtime: Any, base_task: TaskSpec, factory: RTLToGDSFactory, *,
                 cancel_port=None, knowledge_factory: KnowledgeTaskFactory | None = None) -> None:
        base_task.validate(); factory.validate_task(base_task)
        self._runtime, self._base_task, self._factory = runtime, base_task, factory
        self._cancel_port = cancel_port
        self._knowledge_factory = knowledge_factory

    def _binding(self, goal: DesignGoal, state: DesignState, call: SemanticToolCall) -> None:
        L1SemanticToolPolicy.validate(goal, state, call)
        if (self._base_task.project_id != goal.project_id
                or self._base_task.design_id != goal.design_id):
            raise ValueError("Runtime base task does not bind the typed DesignGoal project/design")

    @staticmethod
    def supported_tools() -> frozenset[ToolName]:
        return frozenset({ToolName.GET_DESIGN_SUMMARY, ToolName.QUERY_TIMING, ToolName.QUERY_CONGESTION,
                          ToolName.QUERY_DRC, ToolName.QUERY_POWER, ToolName.QUERY_STAGE_METRICS,
                          ToolName.QUERY_ARTIFACT_EXCERPT, ToolName.SET_FLOW_PARAMS, ToolName.RUN_STAGE,
                          ToolName.QUERY_OPENROAD_KNOWLEDGE, ToolName.RUN_FULL_FLOW,
                          ToolName.COMPARE_RUNS, ToolName.STOP_OR_ESCALATE})

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
                           {"run_id": run_id, "capability": self._factory.capability},
                           (_evidence(f"run:{run_id}", {"goal_id": goal.goal_id, "call_id": call.call_id}),), None)

    def execute(self, goal: DesignGoal, state: DesignState, call: SemanticToolCall) -> ToolReceipt:
        """Dispatch only the tutorial's typed tools; no generic executor exists."""
        if call.tool in {ToolName.RUN_STAGE, ToolName.RUN_FULL_FLOW}:
            return self.submit(goal, state, call)
        if call.tool is ToolName.SET_FLOW_PARAMS:
            return self.set_flow_params(goal, state, call)
        if call.tool is ToolName.STOP_OR_ESCALATE:
            return self.stop_or_escalate(goal, state, call)
        if call.tool is ToolName.GET_DESIGN_SUMMARY:
            return self.design_summary(goal, state, call)
        if call.tool is ToolName.QUERY_OPENROAD_KNOWLEDGE:
            return self.query_openroad_knowledge(goal, state, call)
        return self.query(goal, state, call)

    def query_openroad_knowledge(self, goal: DesignGoal, state: DesignState,
                                 call: SemanticToolCall) -> ToolReceipt:
        """Run one admitted read-only ORAssistant task and return cited facts.

        This deliberately does not enter ``RuntimeObservation`` or the QoR
        reducer: it is a knowledge run, not an EDA measurement. Runtime still
        owns its process lifecycle, terminal status, and registered artifacts.
        """
        self._binding(goal, state, call)
        if call.tool is not ToolName.QUERY_OPENROAD_KNOWLEDGE:
            raise ValueError("knowledge query requires query_openroad_knowledge")
        if self._knowledge_factory is None:
            raise ValueError("no admitted OpenROAD knowledge capability is configured")
        request = KnowledgeQueryRequest(
            project_id=goal.project_id, design_id=goal.design_id,
            query=call.arguments["query"],
            purpose=call.arguments.get("purpose", "knowledge"),
            top_k=call.arguments.get("top_k", 5),
            task_id=f"l1-knowledge-{call.call_id}",
            labels={"l1_goal_id": goal.goal_id, "l1_call_id": call.call_id,
                    "surface": "l1-workbench"},
        )
        task = self._knowledge_factory.build(request)
        self._knowledge_factory.validate_task(task)
        run = self._runtime.submit(task, capability=self._knowledge_factory.capability)
        run_id = getattr(run, "run_id", None)
        if not isinstance(run_id, str) or not run_id:
            raise RuntimeError("Runtime knowledge submission returned no run_id")
        self._runtime.execute_once(run_id)
        view = self._runtime.describe(run_id)
        self._require_owned_run(goal, view)
        terminal = self._terminal_status(view)
        if terminal != "succeeded":
            return ToolReceipt(
                call.call_id, goal.goal_id, state.state_id, call.tool, "failed",
                {"run_id": run_id, "capability": self._knowledge_factory.capability,
                 "terminal_status": terminal},
                (_evidence(f"run:{run_id}", view),),
            )
        artifacts = {
            item.get("kind"): item
            for stage in view.get("stages", ())
            for attempt in stage.get("attempts", ())
            for item in attempt.get("artifacts", ())
            if isinstance(item.get("kind"), str)
        }
        required = {"knowledge_retrieval", "knowledge_explanation",
                    "knowledge_provenance"}
        if not required.issubset(artifacts):
            raise ValueError("Runtime knowledge run lacks required registered artifacts")
        retrieval = self._registered_json(run_id, artifacts["knowledge_retrieval"])
        explanation = self._registered_json(run_id, artifacts["knowledge_explanation"])
        provenance = self._registered_json(run_id, artifacts["knowledge_provenance"])
        retrieval_evidence = self._artifact_evidence(artifacts["knowledge_retrieval"])
        evidence = tuple(self._artifact_evidence(artifacts[kind]) for kind in sorted(required))
        citations = []
        for row in retrieval.get("results", ())[:request.top_k]:
            if not isinstance(row, Mapping):
                raise ValueError("knowledge retrieval result is malformed")
            text = " ".join(str(row.get("text", "")).split())
            citations.append({
                "citation_id": row.get("citation_id"), "rank": row.get("rank"),
                "source_document": row.get("source_path"),
                "source_reference": row.get("source_url"),
                "document_sha256": row.get("document_sha256"),
                "chunk_sha256": row.get("chunk_sha256"),
                "excerpt": text[:1600], "evidence": retrieval_evidence.to_dict(),
            })
        if not citations:
            raise ValueError("knowledge retrieval returned no cited evidence")
        facts = []
        for item in explanation.get("facts") or ():
            if not isinstance(item, Mapping):
                raise ValueError("knowledge explanation fact is malformed")
            facts.append({
                "citation_id": item.get("citation_id"),
                "quote": item.get("quote"),
                "source_document": item.get("source_path"),
            })
        result = {
            "run_id": run_id, "capability": self._knowledge_factory.capability,
            "purpose": request.purpose, "query": request.query.strip(),
            "method": retrieval.get("method"), "citations": citations,
            "facts": facts,
            "hypotheses": list(explanation.get("hypotheses") or ()),
            "counter_evidence": list(explanation.get("counter_evidence") or ()),
            "unknowns": list(explanation.get("unknowns") or ()),
            "diagnostic_claim": explanation.get("diagnostic_claim"),
            "claim_scope": provenance.get("claim_scope"),
        }
        return ToolReceipt(call.call_id, goal.goal_id, state.state_id, call.tool,
                           "completed", result, evidence)

    def _registered_json(self, run_id: str, artifact: Mapping[str, Any]) -> Mapping[str, Any]:
        artifact_id = artifact.get("artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id:
            raise ValueError("registered knowledge artifact lacks identity")
        reader = getattr(self._runtime, "read_artifact_excerpt", None)
        if not callable(reader):
            raise ValueError("Runtime does not expose controlled artifact reads")
        excerpt = reader(run_id, artifact_id, offset=0, max_bytes=64 * 1024)
        try:
            value = json.loads(str(excerpt["text"]))
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("registered knowledge artifact is not bounded JSON") from exc
        if not isinstance(value, Mapping):
            raise ValueError("registered knowledge artifact must contain an object")
        return value

    @staticmethod
    def _artifact_evidence(artifact: Mapping[str, Any]) -> EvidencePointer:
        artifact_id, sha256 = artifact.get("artifact_id"), artifact.get("sha256")
        if (not isinstance(artifact_id, str) or not artifact_id
                or not isinstance(sha256, str) or len(sha256) != 64):
            raise ValueError("registered knowledge artifact lacks hash provenance")
        return EvidencePointer(f"artifact:runtime-{artifact_id}", sha256)

    def set_flow_params(self, goal: DesignGoal, state: DesignState, call: SemanticToolCall) -> ToolReceipt:
        self._binding(goal, state, call)
        values = call.arguments.get("values")
        if call.tool is not ToolName.SET_FLOW_PARAMS or not isinstance(values, Mapping) or not values:
            raise ValueError("set_flow_params requires a non-empty typed values mapping")
        if set(values) - set(goal.allowed_parameters):
            raise ValueError("parameter patch is outside the DesignGoal policy")
        task = self._factory.reconfigure(self._base_task, values)
        # This is a validated proposal, not an execution result.  S4 persists
        # it in the plan/trace and supplies the same patch to a subsequent
        # RUN_* call; claiming a completed EDA change here would be false.
        proposal_sha256 = hashlib.sha256(json.dumps(task.to_dict(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return ToolReceipt(call.call_id, goal.goal_id, state.state_id, call.tool, "accepted",
                           {"proposal_id": f"proposal-{call.call_id}", "parameter_patch": dict(values), "task_spec_sha256": proposal_sha256,
                            "requires_following_run": True}, (goal.rtl_artifact,), None)

    def stop_or_escalate(self, goal: DesignGoal, state: DesignState, call: SemanticToolCall) -> ToolReceipt:
        self._binding(goal, state, call)
        run_id = call.arguments.get("run_id")
        if call.tool is not ToolName.STOP_OR_ESCALATE or not isinstance(run_id, str) or not run_id:
            raise ValueError("stop_or_escalate requires a Runtime run_id")
        view = self._runtime.describe(run_id)
        labels = view.get("run", {}).get("task_spec", {}).get("labels", {})
        if labels.get("l1_goal_id") != goal.goal_id:
            raise ValueError("Runtime run is not owned by this DesignGoal")
        if not callable(self._cancel_port):
            raise ValueError("Runtime does not expose controlled cancellation")
        self._cancel_port(run_id)
        return ToolReceipt(call.call_id, goal.goal_id, state.state_id, call.tool, "accepted",
                           {"run_id": run_id, "action": "cancel_requested"}, (_evidence(f"run:{run_id}", view),), None)

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
        # Runtime's describe payload includes implementation-only workspace and
        # store-key details.  It is evidence for this bridge, never a L1/UI
        # payload.  Every read tool below returns a deliberately small,
        # tool-specific projection of registered Runtime facts instead.
        result: dict[str, Any] = self._read_projection(call, views)
        if call.tool is ToolName.QUERY_ARTIFACT_EXCERPT:
            result = {"run_id": run_ids[0], **self._read_excerpt(run_ids[0], call.arguments["artifact_id"],
                                                    offset=call.arguments.get("offset", 0), max_bytes=call.arguments["max_bytes"])}
        return ToolReceipt(call.call_id, goal.goal_id, state.state_id, call.tool, "completed",
                           result,
                           tuple(_evidence(f"run:{run_id}", view) for run_id, view in views.items()))

    def observation(self, run_id: str) -> RuntimeObservation:
        view = self._runtime.describe(run_id); run = view["run"]
        if run.get("status") not in {"succeeded", "failed", "cancelled", "timed_out", "lost"}:
            raise ValueError("Runtime observation requires a terminal run")
        candidates = [(stage, attempt) for stage in view.get("stages", ()) for attempt in stage.get("attempts", ())
                      if (run["status"] == "succeeded" and stage.get("successful_attempt_id") == attempt.get("attempt_id"))
                      or (run["status"] != "succeeded" and attempt.get("status") in {run["status"], run.get("terminal_reason")})]
        if len(candidates) != 1:
            raise ValueError("Runtime run has no attempt observation")
        stage_view, attempt = candidates[0]
        metrics, official_artifact = self._canonical_qor(attempt)
        evidence = tuple(
            EvidencePointer(f"artifact:runtime-{item['artifact_id']}", item["sha256"])
            if isinstance(item.get("sha256"), str) and len(item["sha256"]) == 64
            else _evidence(f"artifact:runtime-{item['artifact_id']}", item)
            for item in attempt.get("artifacts", ())
        )
        if official_artifact is not None:
            official_ref = f"artifact:runtime-{official_artifact['artifact_id']}"
            evidence = tuple(sorted(evidence, key=lambda item: item.ref != official_ref))
        if not evidence:
            evidence = (_evidence(f"run:{run_id}", view),)
        terminal_status = run.get("terminal_reason") if run.get("terminal_reason") in {"timed_out", "lost"} else run["status"]
        stage = stage_view.get("stage_key")
        if stage not in {"synth", "floorplan", "place", "cts", "route", "finish"}:
            stage = None
        return RuntimeObservation(run_id, attempt["attempt_id"], stage, terminal_status, metrics, evidence)

    @staticmethod
    def _canonical_qor(attempt: Mapping[str, Any]) -> tuple[dict[str, float], Mapping[str, Any] | None]:
        """Read only Runtime-attested protected-evaluator metadata as state QoR."""
        official = [
            item for item in attempt.get("artifacts", ())
            if item.get("metadata", {}).get("runtime_authority") == "protected_evaluator"
            and item.get("metadata", {}).get("producer") == "protected-orfs-evaluator"
            and item.get("metadata", {}).get("official_qor") is True
            and item.get("metadata", {}).get("outcome") == "completed"
        ]
        if not official:
            return {}, None
        if len(official) != 1:
            raise ValueError("Runtime attempt has ambiguous protected evaluator artifacts")
        artifact = official[0]
        metadata = artifact.get("metadata", {})
        values = metadata.get("canonical_metrics")
        if (not isinstance(values, Mapping)
                or not isinstance(metadata.get("evaluation_id"), str)
                or not isinstance(artifact.get("sha256"), str)
                or len(artifact["sha256"]) != 64):
            raise ValueError("protected evaluator artifact lacks canonical metric provenance")
        metrics: dict[str, float] = {}
        for name, value in values.items():
            if (not isinstance(name, str) or not name
                    or isinstance(value, bool) or not isinstance(value, (int, float))):
                raise ValueError("protected evaluator canonical metrics are invalid")
            metrics[name] = float(value)
        return metrics, artifact

    def reduce_and_trace(self, trace: L1TraceService, trace_id: str, state: DesignState,
                         *, run_id: str, next_state_id: str, consume_eda_run: bool = False) -> DesignState:
        """The only S3 handoff from Runtime facts into the S2 state authority."""
        observation = self.observation(run_id)
        self._require_owned_run_from_id(state.goal_id, run_id)
        successor = L1StateReducer.apply(state, observation, next_state_id=next_state_id,
                                         consume_eda_run=consume_eda_run)
        trace.record_observation(trace_id, state, successor, observation,
                                 consume_eda_run=consume_eda_run)
        return successor

    @classmethod
    def _read_projection(cls, call: SemanticToolCall, views: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
        """Return visible Runtime facts without a workspace, log, or command.

        A trace is a teaching/audit record rather than a Runtime debugging
        dump.  The raw describe response remains inside the Runtime boundary;
        references and hashes in the receipt evidence point back to it.
        """
        run_ids = tuple(views)
        if call.tool is ToolName.COMPARE_RUNS:
            names = tuple(call.arguments["metrics"])
            metrics = {run_id: cls._metrics(view) for run_id, view in views.items()}
            return {"left_run_id": run_ids[0], "right_run_id": run_ids[1],
                    "metrics": {name: {run_id: metrics[run_id].get(name) for run_id in run_ids}
                                for name in names}}
        category = {
            ToolName.QUERY_TIMING: ("timing", "wns", "tns", "slack", "delay"),
            ToolName.QUERY_CONGESTION: ("congestion", "overflow", "density", "utilization"),
            ToolName.QUERY_DRC: ("drc", "violation", "antenna"),
            ToolName.QUERY_POWER: ("power", "ir_drop", "voltage"),
        }.get(call.tool)
        rows = []
        for run_id, view in views.items():
            metrics = cls._metrics(view)
            selected = (metrics if call.tool is ToolName.QUERY_STAGE_METRICS else
                        {name: value for name, value in metrics.items()
                         if category and any(term in name.lower() for term in category)})
            limit = call.arguments.get("limit")
            if limit is not None:
                selected = dict(list(sorted(selected.items()))[:limit])
            rows.append({"run_id": run_id, "terminal_status": cls._terminal_status(view),
                         "metrics": selected})
        return {"runs": rows}

    @staticmethod
    def _terminal_status(view: Mapping[str, Any]) -> str:
        run = view.get("run", {})
        return str(run.get("terminal_reason") or run.get("status") or "unknown")

    @staticmethod
    def _metrics(view: Mapping[str, Any]) -> dict[str, float]:
        aliases = {
            "finish__timing__setup__ws": "setup_wns_ns",
            "finish__design__instance__area": "area_um2",
            "detailedroute__route__drc_errors": "drc_errors",
        }
        return {aliases.get(item["name"], item["name"]): float(item["value"])
                for stage in view.get("stages", ()) for attempt in stage.get("attempts", ())
                for item in attempt.get("metrics", ())
                if isinstance(item.get("value"), (int, float)) and not isinstance(item.get("value"), bool)}

    def _read_excerpt(self, run_id: str, artifact_id: str, *, offset: int,
                      max_bytes: int) -> dict:
        reader = getattr(self._runtime, "read_artifact_excerpt", None)
        if not callable(reader):
            raise ValueError("Runtime does not expose controlled artifact excerpt access")
        return dict(reader(run_id, artifact_id, offset=offset, max_bytes=max_bytes))

    @staticmethod
    def _require_owned_run(goal: DesignGoal, view: Mapping[str, Any]) -> None:
        if view.get("run", {}).get("task_spec", {}).get("labels", {}).get("l1_goal_id") != goal.goal_id:
            raise ValueError("Runtime run is not owned by this DesignGoal")

    def _require_owned_run_from_id(self, goal_id: str, run_id: str) -> None:
        view = self._runtime.describe(run_id)
        if view.get("run", {}).get("task_spec", {}).get("labels", {}).get("l1_goal_id") != goal_id:
            raise ValueError("Runtime run is not owned by this DesignGoal")
