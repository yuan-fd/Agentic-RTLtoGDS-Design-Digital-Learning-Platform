"""Stateful L2 policy layer: evidence selects a subspace, BO selects numbers.

The module is intentionally separate from ``optimizer_plugins``.  It neither
executes OpenROAD nor asks an LLM for numeric parameters.  An LLM policy may
select one of the typed modes through L1's ``propose_search_policy`` tool; this
module verifies that choice against observed state and delegates numerical
candidate generation to the existing BO/TPE/Sobol plugins.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping

from openroad_platform_contracts import (
    DesignState, LearningObservation, OptimizationStudy, OptimizerProposal,
    SemanticToolCall, ToolName,
)

from .optimizer_plugins import (
    AdaptiveTrustRegionQNEHVIOptimizer, BoTorchQNEHVIOptimizer,
    OptimizerBackend, SobolOptimizer,
)


class SearchMode(str, Enum):
    FEASIBILITY_RECOVERY = "feasibility_recovery"
    GLOBAL_EXPLORATION = "global_exploration"
    INTERACTION_SCREENING = "interaction_screening"
    LOCAL_TRUST_REGION = "local_trust_region"
    COST_AWARE_PROMOTION = "cost_aware_promotion"
    REPLICATED_CONFIRMATION = "replicated_confirmation"


def compact_policy_evidence(
    evidence: Iterable[EvidencePointer], *, maximum: int = 8,
) -> tuple[EvidencePointer, ...]:
    """Keep an L1 policy prompt addressable without discarding provenance.

    A Runtime observation can contain dozens of low-level artifact pointers.
    They remain authoritative in EDAIR and the Runtime, but copying all of
    them into every policy decision neither adds independent evidence nor
    leaves a bounded context for a language model.  This helper retains a
    small, deterministic *index*: run-level evidence first, then the study
    source, then a limited set of directly addressable artifacts.  It never
    rewrites an evidence hash or deletes the original observation evidence.
    """
    if not 1 <= maximum <= 64:
        raise ValueError("policy evidence maximum must be between 1 and 64")
    unique: list[EvidencePointer] = []
    seen: set[tuple[str, str]] = set()
    for pointer in evidence:
        pointer.validate()
        identity = (pointer.ref, pointer.sha256)
        if identity not in seen:
            unique.append(pointer)
            seen.add(identity)

    def priority(pointer: EvidencePointer) -> tuple[int, str, str]:
        # An EDAIR packet is already a loss-accounted interface.  In its
        # absence a run id is the best durable handle for typed query tools.
        if pointer.ref.startswith("edair:"):
            tier = 0
        elif pointer.ref.startswith("run:"):
            tier = 1
        elif pointer.ref.startswith("source:study:"):
            tier = 2
        elif pointer.ref.startswith("artifact:"):
            tier = 3
        else:
            tier = 4
        return (tier, pointer.ref, pointer.sha256)

    return tuple(sorted(unique, key=priority)[:maximum])


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _is_feasible(observation: LearningObservation,
                 constraints: tuple[dict[str, Any], ...]) -> bool:
    if observation.status != "succeeded":
        return False
    for rule in constraints:
        value = observation.metrics.get(str(rule["metric"]))
        if value is None or not math.isfinite(float(value)):
            return False
        threshold = float(rule["threshold"])
        if rule["operator"] == ">=" and float(value) < threshold:
            return False
        if rule["operator"] == "<=" and float(value) > threshold:
            return False
        if rule["operator"] == "==" and float(value) != threshold:
            return False
    return True


@dataclass(frozen=True)
class SearchPolicyDecision:
    """A bounded strategy decision, never a numerical candidate proposal."""

    mode: SearchMode
    parameter_subset: tuple[str, ...]
    hypothesis: str
    stop_condition: str
    evidence_refs: tuple[str, ...]
    source: str = "deterministic-state-policy"

    def validate(self, study: OptimizationStudy) -> None:
        study.validate()
        names = {item.name for item in study.parameter_space}
        if not self.parameter_subset or len(set(self.parameter_subset)) != len(self.parameter_subset):
            raise ValueError("search policy requires a unique non-empty parameter subset")
        if any(item not in names for item in self.parameter_subset):
            raise ValueError("search policy contains parameter outside study")
        for name, value, maximum in (("hypothesis", self.hypothesis, 2000),
                                     ("stop_condition", self.stop_condition, 1000),
                                     ("source", self.source, 128)):
            if not isinstance(value, str) or not value.strip() or len(value) > maximum:
                raise ValueError(f"search policy {name} is invalid")
        if not self.evidence_refs or not all(isinstance(item, str) and item for item in self.evidence_refs):
            raise ValueError("search policy requires evidence references")

    def to_dict(self) -> dict[str, Any]:
        return {"mode": self.mode.value, "parameter_subset": list(self.parameter_subset),
                "hypothesis": self.hypothesis, "stop_condition": self.stop_condition,
                "evidence_refs": list(self.evidence_refs), "source": self.source}

    @classmethod
    def from_l1_call(cls, call: SemanticToolCall, study: OptimizationStudy) -> "SearchPolicyDecision":
        call.validate(); study.validate()
        # The L1 ``propose_search_policy`` tool was retired from the platform
        # surface; this decoder is kept for historical study records only.
        if call.tool.value != "propose_search_policy":
            raise ValueError("only historical L1 propose_search_policy calls may decode an L2 strategy")
        arguments = call.arguments
        result = cls(
            mode=SearchMode(str(arguments["mode"])),
            parameter_subset=tuple(str(item) for item in arguments["parameter_subset"]),
            hypothesis=str(arguments["hypothesis"]),
            stop_condition=str(arguments["stop_condition"]),
            evidence_refs=tuple(item.ref for item in call.evidence),
            source=f"l1:{call.producer}",
        )
        result.validate(study)
        return result


class EvidenceBoundSearchPolicy:
    """Deterministic fallback when no admissible LLM policy is supplied.

    This keeps the optimizer operational but never pretends that a heuristic is
    an LLM explanation.  The choice and all evidence are emitted in proposal
    metadata, making later ablation of the policy layer straightforward.
    """

    def decide(self, study: OptimizationStudy, state: DesignState,
               observations: Iterable[LearningObservation], *,
               memory_snapshot: Mapping[str, Any] | None = None,
               stall_window: int = 3) -> SearchPolicyDecision:
        study.validate(); state.validate()
        rows = tuple(observations)
        evidence = [item.ref for item in compact_policy_evidence(
            (*state.evidence,
             *((state.edair_ref,) if state.edair_ref is not None else ())),
        )]
        if not evidence:
            raise ValueError("stateful search policy requires evidence-backed DesignState")
        parameter_names = tuple(item.name for item in study.parameter_space)
        feasible = [item for item in rows if _is_feasible(item, study.hard_constraints)]
        if not feasible:
            return SearchPolicyDecision(
                SearchMode.FEASIBILITY_RECOVERY, parameter_names,
                "No observed configuration satisfies every hard constraint; recover a feasible region before trading PPA.",
                "stop after the configured feasibility budget or after a replicated feasible anchor is observed.",
                tuple(evidence),
            )
        active_interactions = [item for item in (memory_snapshot or {}).get("active_artifacts", [])
                               if item.get("kind") == "parameter_interaction"]
        if active_interactions:
            subset = tuple(str(item) for item in active_interactions[0].get("payload", {}).get("parameters", ())
                           if item in parameter_names)
            if subset:
                return SearchPolicyDecision(
                    SearchMode.INTERACTION_SCREENING, subset,
                    "A holdout-corroborated interaction is active; estimate the coupled subspace before widening search.",
                    "stop after the planned interaction batch; retire the hypothesis if its holdout direction reverses.",
                    tuple(evidence),
                )
        if self._stalled(study, rows, stall_window=stall_window):
            stage = str((state.diagnosis or {}).get("dominant_stage") or "")
            subset = tuple(item.name for item in study.parameter_space if item.stage == stage)
            return SearchPolicyDecision(
                SearchMode.LOCAL_TRUST_REGION, subset or parameter_names,
                "Replicated feasible utility has stalled; locally refine the evidence-indicated stage around the best safe point.",
                "leave the local region after three non-improving batches or radius exhaustion.",
                tuple(evidence),
            )
        return SearchPolicyDecision(
            SearchMode.GLOBAL_EXPLORATION, parameter_names,
            "The feasible frontier remains underexplored; use global constrained multi-objective search.",
            "switch when the stall rule fires, a supported interaction appears, or budget reaches the promotion checkpoint.",
            tuple(evidence),
        )

    @staticmethod
    def _stalled(study: OptimizationStudy, rows: tuple[LearningObservation, ...], *,
                 stall_window: int) -> bool:
        if stall_window < 1:
            raise ValueError("stall_window must be positive")
        grouped: dict[str, list[LearningObservation]] = {}
        for item in rows:
            if item.context.flow_stage != "finish" or not _is_feasible(item, study.hard_constraints):
                continue
            grouped.setdefault(_digest(item.parameters), []).append(item)
        scores = []
        for values in grouped.values():
            if not values:
                continue
            score = 0.0
            for objective in study.objectives:
                metric = [float(item.metrics[objective.metric_name]) for item in values
                          if objective.metric_name in item.metrics]
                if not metric:
                    break
                direction = 1.0 if objective.direction == "max" else -1.0
                score += direction * float(objective.weight) * float(sum(metric) / len(metric))
            else:
                scores.append(score)
        if len(scores) < stall_window + 1:
            return False
        best_before = max(scores[:-stall_window])
        return max(scores[-stall_window:]) <= best_before


class StatefulL2Controller:
    """Coordinate policy-selected subspaces with numerical BO proposals."""

    def __init__(self, policy: EvidenceBoundSearchPolicy | None = None, *,
                 minimum_initial: int | None = None):
        self.policy = policy or EvidenceBoundSearchPolicy()
        self.minimum_initial = minimum_initial

    def propose(self, study: OptimizationStudy, state: DesignState,
                observations: Iterable[LearningObservation], *, batch_size: int,
                baseline_metrics: dict[str, float],
                decision: SearchPolicyDecision | None = None,
                memory_snapshot: Mapping[str, Any] | None = None,
                historical_observations: Iterable[LearningObservation] = (),
                excluded_parameters: Iterable[dict[str, Any]] = (),
                iteration_start: int | None = None) -> tuple[OptimizerProposal, ...]:
        rows = tuple(observations)
        selected = decision or self.policy.decide(
            study, state, rows, memory_snapshot=memory_snapshot)
        selected.validate(study)
        if selected.mode is SearchMode.REPLICATED_CONFIRMATION:
            raise ValueError("replicated confirmation is a scheduler replay action, not a candidate generator")
        scoped = self._scoped_study(study, selected.parameter_subset)
        scoped_rows = tuple(self._project_observation(item, scoped) for item in rows)
        scoped_history = tuple(self._project_observation(item, scoped)
                               for item in historical_observations)
        backend = self._backend(selected.mode)
        proposals = backend.propose_batch(
            scoped, scoped_rows, batch_size=batch_size, baseline_metrics=baseline_metrics,
            historical_observations=scoped_history,
            excluded_parameters=tuple(self._project_parameters(item, scoped)
                                      for item in excluded_parameters),
            iteration_start=iteration_start,
        )
        return tuple(dataclasses.replace(
            proposal,
            model_metadata={**proposal.model_metadata, "state_tuning": selected.to_dict(),
                            "full_study_id": study.study_id,
                            "subspace_fingerprint": _digest(
                                [item.name for item in scoped.parameter_space])},
        ) for proposal in proposals)

    def _backend(self, mode: SearchMode) -> OptimizerBackend:
        if mode is SearchMode.FEASIBILITY_RECOVERY:
            return SobolOptimizer()
        if mode is SearchMode.LOCAL_TRUST_REGION:
            return AdaptiveTrustRegionQNEHVIOptimizer(minimum_initial=self.minimum_initial)
        return BoTorchQNEHVIOptimizer(minimum_initial=self.minimum_initial)

    @staticmethod
    def _scoped_study(study: OptimizationStudy,
                      names: tuple[str, ...]) -> OptimizationStudy:
        chosen = set(names)
        by_name = {item.name: item for item in study.parameter_space}
        changed = True
        while changed:
            changed = False
            for name in tuple(chosen):
                item = by_name[name]
                dependencies = set(item.active_when)
                if item.less_than_or_equal_to:
                    dependencies.add(item.less_than_or_equal_to)
                for dependency in dependencies:
                    if dependency not in chosen:
                        chosen.add(dependency); changed = True
        parameters = tuple(item for item in study.parameter_space if item.name in chosen)
        return dataclasses.replace(study, parameter_space=parameters)

    @staticmethod
    def _project_parameters(parameters: Mapping[str, Any],
                            study: OptimizationStudy) -> dict[str, Any]:
        return {item.name: parameters[item.name] for item in study.parameter_space
                if item.name in parameters}

    @classmethod
    def _project_observation(cls, observation: LearningObservation,
                             study: OptimizationStudy) -> LearningObservation:
        return dataclasses.replace(observation,
                                   parameters=cls._project_parameters(observation.parameters, study))