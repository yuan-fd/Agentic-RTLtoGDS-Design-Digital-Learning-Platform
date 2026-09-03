"""Pluggable industrial DSE backends; proposals never execute a flow."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from typing import Any, Iterable, Protocol, Sequence

import numpy as np

from openroad_platform_contracts import (
    EvidencePointer, LearningObservation, OptimizationStudy, OptimizerProposal,
    ParameterSpec, Prediction,
)


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class OptimizerBackend(Protocol):
    backend_id: str

    def propose_batch(self, study: OptimizationStudy,
                      observations: Iterable[LearningObservation], *,
                      batch_size: int, baseline_metrics: dict[str, float],
                      historical_observations: Iterable[LearningObservation] = (),
                      excluded_parameters: Iterable[dict[str, Any]] = (),
                      iteration_start: int | None = None,
                      ) -> tuple[OptimizerProposal, ...]: ...


def _merge_current_and_history(
    current: Sequence[LearningObservation],
    historical: Iterable[LearningObservation],
) -> tuple[LearningObservation, ...]:
    """Add immutable priors without charging them to the current-study budget."""
    seen = {item.observation_id for item in current}
    return tuple(current) + tuple(
        item for item in historical if item.observation_id not in seen)


_INFRASTRUCTURE_FAILURE_CATEGORIES = frozenset({
    "adapter_error", "cancelled", "protocol_error", "runtime_error",
    "transient_io", "worker_lost",
})


def _observation_is_infrastructure_failure(
    observation: LearningObservation,
) -> bool:
    """Separate execution infrastructure faults from design infeasibility.

    Lost/cancelled work and controller/adapter/worker failures are retained in
    the immutable experiment ledger, but are neither negative feasibility
    labels nor evidence for portfolio routing.  ORFS failures and timeouts are
    deliberately *not* listed here: under the frozen experiment contract they
    are configuration-cost/failure outcomes unless the controller invalidates
    the complete cell.
    """
    return (observation.status in {"lost", "cancelled"}
            or observation.failure_category in
            _INFRASTRUCTURE_FAILURE_CATEGORIES)


def _observation_is_feasible(
    observation: LearningObservation,
    constraints: Sequence[dict[str, Any]],
) -> bool:
    if observation.status != "succeeded":
        return False
    for rule in constraints:
        value = observation.metrics.get(str(rule["metric"]))
        if value is None or not math.isfinite(float(value)):
            return False
        threshold = float(rule["threshold"])
        operator = rule["operator"]
        if operator == ">=" and not float(value) >= threshold:
            return False
        if operator == "<=" and not float(value) <= threshold:
            return False
        if operator == "==" and not float(value) == threshold:
            return False
    return True


def _constraint_residuals(
    observation: LearningObservation,
    constraints: Sequence[dict[str, Any]],
) -> tuple[float, ...]:
    """Return Optuna residuals, where every value <= 0 is feasible."""
    if observation.status != "succeeded":
        return tuple(1.0 for _ in constraints)
    residuals = []
    for rule in constraints:
        raw = observation.metrics.get(str(rule["metric"]))
        if raw is None or not math.isfinite(float(raw)):
            residuals.append(1.0)
            continue
        value, threshold = float(raw), float(rule["threshold"])
        if rule["operator"] == ">=":
            residuals.append(threshold - value)
        elif rule["operator"] == "<=":
            residuals.append(value - threshold)
        else:
            residuals.append(abs(value - threshold))
    return tuple(residuals)


def _replicated_feasible_anchors(
    observations: Sequence[LearningObservation],
    constraints: Sequence[dict[str, Any]], *, minimum_replicas: int = 2,
) -> list[tuple[dict[str, Any], int]]:
    """Return finish configurations whose observed replicas all pass.

    A single lucky OR_SEED must not become a safety anchor when another
    physical replica of the same configuration violates timing or DRC.  Quick
    fidelity observations and infrastructure failures are not evidence either
    way; configuration-caused failures are evidence against the anchor.
    """
    grouped: dict[str, list[LearningObservation]] = {}
    order: list[str] = []
    for item in observations:
        if (item.context.flow_stage != "finish"
                or _observation_is_infrastructure_failure(item)):
            continue
        key = _digest(item.parameters)
        if key not in grouped:
            order.append(key)
        grouped.setdefault(key, []).append(item)
    anchors = []
    for key in order:
        replicas = grouped[key]
        if (len(replicas) >= minimum_replicas
                and all(_observation_is_feasible(item, constraints)
                        for item in replicas)):
            anchors.append((dict(replicas[0].parameters), len(replicas)))
    return anchors


@dataclass(frozen=True)
class MixedParameterEncoder:
    specs: tuple[ParameterSpec, ...]

    @property
    def encoded_dimension(self) -> int:
        return sum(len(spec.choices) if spec.kind == "categorical" else 1 for spec in self.specs)

    def decode_unit(self, row: Sequence[float]) -> dict[str, Any]:
        if len(row) != len(self.specs):
            raise ValueError("Unit candidate dimensionality mismatch")
        provisional: dict[str, Any] = {}
        for spec, raw in zip(self.specs, row):
            value = min(max(float(raw), 0.0), np.nextafter(1.0, 0.0))
            if spec.kind == "categorical":
                decoded = spec.choices[min(int(value * len(spec.choices)), len(spec.choices) - 1)]
            elif spec.kind == "bool":
                decoded = int(value >= .5)
            else:
                assert spec.lower is not None and spec.upper is not None
                decoded = spec.lower + value * (spec.upper - spec.lower)
                step = spec.step or (1 if spec.kind == "int" else None)
                if step:
                    decoded = spec.lower + round((decoded - spec.lower) / step) * step
                decoded = min(max(decoded, spec.lower), spec.upper)
                if spec.kind == "int":
                    decoded = int(round(decoded))
                else:
                    decoded = float(decoded)
            provisional[spec.name] = decoded
        provisional = self.project_relations(provisional)
        return {spec.name: provisional[spec.name] for spec in self.specs
                if not spec.active_when or all(provisional.get(key) == value
                                               for key, value in spec.active_when.items())}

    def project_relations(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Project a plugin proposal into the shared legal typed domain."""
        projected = dict(parameters)
        for spec in self.specs:
            if spec.less_than_or_equal_to and spec.name in projected:
                target = projected.get(spec.less_than_or_equal_to)
                if target is None:
                    raise ValueError(
                        f"relational target missing from proposal: {spec.less_than_or_equal_to}")
                projected[spec.name] = min(projected[spec.name], target)
        return projected

    def encode(self, parameters: dict[str, Any]) -> np.ndarray:
        values: list[float] = []
        for spec in self.specs:
            active = not spec.active_when or all(parameters.get(key) == value
                                                 for key, value in spec.active_when.items())
            value = parameters.get(spec.name)
            if spec.kind == "categorical":
                values.extend(float(active and value == choice) for choice in spec.choices)
            elif not active:
                values.append(0.0)
            elif spec.kind == "bool":
                values.append(float(bool(value)))
            else:
                assert spec.lower is not None and spec.upper is not None
                values.append((float(value) - spec.lower) / (spec.upper - spec.lower))
        return np.asarray(values, dtype=float)

    def sobol_candidates(self, count: int, *, seed: int) -> list[dict[str, Any]]:
        from scipy.stats import qmc
        engine = qmc.Sobol(d=len(self.specs), scramble=True, seed=seed)
        raw = engine.random_base2(int(np.ceil(np.log2(max(count, 2)))))[:count]
        unique: dict[str, dict[str, Any]] = {}
        for row in raw:
            candidate = self.decode_unit(row)
            unique.setdefault(_digest(candidate), candidate)
        return list(unique.values())

    def anchored_sobol_candidates(self, count: int, *, seed: int,
                                  anchor: dict[str, Any]) -> list[dict[str, Any]]:
        """Build a one-factor-at-a-time Sobol design around a proven point.

        The first cold-start batches deliberately identify main effects before
        sampling high-order combinations.  This does not claim that the local
        points are feasible: each point still consumes budget and passes the
        normal quick/full gates.  It only avoids changing every knob at once
        when the platform already has a hard-constraint-feasible anchor.
        """
        if count < 1:
            return []
        from scipy.stats import qmc
        dimension = len(self.specs)
        center = self.unit_coordinates(anchor)
        target = max(count * 2, dimension * 4, 8)
        engine = qmc.Sobol(d=dimension, scramble=True, seed=seed)
        raw = engine.random_base2(int(np.ceil(np.log2(target))))[:target]
        unique: dict[str, dict[str, Any]] = {}
        for index, row in enumerate(raw):
            coordinates = center.copy()
            coordinates[index % dimension] = row[index % dimension]
            candidate = self.decode_unit(coordinates)
            unique.setdefault(_digest(candidate), candidate)
            if len(unique) >= count:
                break
        # Degenerate categorical/quantized spaces may not yield enough local
        # points. Fill deterministically with global Sobol without duplicates.
        if len(unique) < count:
            for candidate in self.sobol_candidates(target, seed=seed + 1_000_003):
                unique.setdefault(_digest(candidate), candidate)
                if len(unique) >= count:
                    break
        return list(unique.values())

    def unit_coordinates(self, parameters: dict[str, Any]) -> np.ndarray:
        """Inverse coordinates for the one-scalar-per-spec sampling domain."""
        values = []
        for spec in self.specs:
            value = parameters.get(spec.name)
            if spec.kind == "categorical":
                index = spec.choices.index(value) if value in spec.choices else 0
                values.append((index + .5) / len(spec.choices))
            elif spec.kind == "bool":
                values.append(.75 if bool(value) else .25)
            else:
                assert spec.lower is not None and spec.upper is not None
                values.append((float(value) - spec.lower) / (spec.upper - spec.lower))
        return np.clip(np.asarray(values, dtype=float), 0, 1)

    def trust_region_candidates(self, count: int, *, seed: int,
                                center: dict[str, Any], radius: float,
                                stage_focus: str | None = None) \
            -> list[dict[str, Any]]:
        if not 0 < radius <= 1:
            raise ValueError("trust-region radius must be in (0,1]")
        from scipy.stats import qmc
        center_unit = self.unit_coordinates(center)
        engine = qmc.Sobol(d=len(self.specs), scramble=True, seed=seed)
        raw = engine.random_base2(int(np.ceil(np.log2(max(count, 2)))))[:count]
        radii = np.asarray([
            radius if stage_focus is None or spec.stage == stage_focus else radius * .25
            for spec in self.specs
        ])
        lower = np.maximum(0.0, center_unit - radii)
        upper = np.minimum(1.0, center_unit + radii)
        scaled = lower + raw * (upper - lower)
        unique: dict[str, dict[str, Any]] = {_digest(center): dict(center)}
        for row in scaled:
            candidate = self.decode_unit(row)
            unique.setdefault(_digest(candidate), candidate)
        return list(unique.values())


class SobolOptimizer:
    backend_id = "sobol-scrambled-mixed-v1"

    def __init__(self, *, forbidden_configuration_ids: Iterable[str] = ()):
        self.forbidden_configuration_ids = frozenset(forbidden_configuration_ids)

    def propose_batch(self, study: OptimizationStudy,
                      observations: Iterable[LearningObservation], *, batch_size: int,
                      baseline_metrics: dict[str, float],
                      historical_observations: Iterable[LearningObservation] = (),
                      excluded_parameters: Iterable[dict[str, Any]] = (),
                      iteration_start: int | None = None,
                      ) -> tuple[OptimizerProposal, ...]:
        del baseline_metrics
        study.validate()
        current = tuple(observations)
        items = _merge_current_and_history(current, historical_observations)
        encoder = MixedParameterEncoder(study.parameter_space)
        seen = ({_digest(item.parameters) for item in items}
                | {_digest(item) for item in excluded_parameters})
        pool = [item for item in encoder.sobol_candidates(
            max(64, batch_size * 16), seed=study.seed + len(items),
        ) if _digest(item) not in seen and _digest(item) not in self.forbidden_configuration_ids]
        if len(pool) < batch_size:
            raise ValueError("Sobol pool has too few unobserved effective candidates")
        start = len(current) if iteration_start is None else iteration_start
        return tuple(_proposal(study, item, start + index, self.backend_id, 0.0,
                               source_observations=items)
                              for index, item in enumerate(pool[:batch_size]))


class SafeAnchoredSobolOptimizer:
    """Cold-start plugin that expands from observed feasible configurations."""

    backend_id = "safe-anchored-sobol-mixed-v1"

    def __init__(self, *, forbidden_configuration_ids: Iterable[str] = (),
                 minimum_anchor_replicas: int = 2):
        if not 2 <= minimum_anchor_replicas <= 8:
            raise ValueError("minimum_anchor_replicas must be between 2 and 8")
        self.forbidden_configuration_ids = frozenset(forbidden_configuration_ids)
        self.minimum_anchor_replicas = int(minimum_anchor_replicas)

    def propose_batch(self, study: OptimizationStudy,
                      observations: Iterable[LearningObservation], *, batch_size: int,
                      baseline_metrics: dict[str, float],
                      historical_observations: Iterable[LearningObservation] = (),
                      excluded_parameters: Iterable[dict[str, Any]] = (),
                      iteration_start: int | None = None,
                      ) -> tuple[OptimizerProposal, ...]:
        del baseline_metrics
        study.validate()
        current = tuple(observations)
        items = _merge_current_and_history(current, historical_observations)
        anchors = _replicated_feasible_anchors(
            items, study.hard_constraints,
            minimum_replicas=self.minimum_anchor_replicas)
        if not anchors:
            return SobolOptimizer(
                forbidden_configuration_ids=self.forbidden_configuration_ids,
            ).propose_batch(
                study, current, batch_size=batch_size,
                baseline_metrics={}, historical_observations=historical_observations,
                excluded_parameters=excluded_parameters,
                iteration_start=iteration_start,
            )
        encoder = MixedParameterEncoder(study.parameter_space)
        seen = ({_digest(item.parameters) for item in items}
                | {_digest(item) for item in excluded_parameters})
        anchor, anchor_replica_count = anchors[0]
        pool = [item for item in encoder.anchored_sobol_candidates(
            max(64, batch_size * 16), seed=study.seed + len(items), anchor=anchor,
        ) if _digest(item) not in seen
            and _digest(item) not in self.forbidden_configuration_ids]
        if len(pool) < batch_size:
            raise ValueError("Safe anchored Sobol pool has too few unobserved candidates")
        start = len(current) if iteration_start is None else iteration_start
        metadata = {
            "backend_id": self.backend_id, "has_fitted_surrogate": False,
            "initialization": "feasible-anchor one-factor-at-a-time Sobol",
            "anchor_configuration_sha256": _digest(anchor),
            "anchor_observed_feasible": True,
            "anchor_replica_count": anchor_replica_count,
            "anchor_policy": "all required observed finish replicas feasible",
            "minimum_anchor_replicas": self.minimum_anchor_replicas,
            "high_order_interactions_deferred": True,
        }
        return tuple(_proposal(
            study, item, start + index, self.backend_id, 0.0,
            source_observations=items, model_metadata=metadata,
        ) for index, item in enumerate(pool[:batch_size]))


class RandomOptimizer:
    backend_id = "seeded-random-mixed-v1"

    def propose_batch(self, study: OptimizationStudy,
                      observations: Iterable[LearningObservation], *, batch_size: int,
                      baseline_metrics: dict[str, float],
                      historical_observations: Iterable[LearningObservation] = (),
                      excluded_parameters: Iterable[dict[str, Any]] = (),
                      iteration_start: int | None = None,
                      ) -> tuple[OptimizerProposal, ...]:
        del baseline_metrics
        current = tuple(observations)
        items = _merge_current_and_history(current, historical_observations)
        rng = np.random.default_rng(study.seed + len(current) * 7919)
        encoder = MixedParameterEncoder(study.parameter_space)
        seen = ({_digest(item.parameters) for item in items}
                | {_digest(item) for item in excluded_parameters})
        unique = {}
        for row in rng.random((max(256, batch_size * 32), len(study.parameter_space))):
            parameters = encoder.decode_unit(row)
            key = _digest(parameters)
            if key not in seen:
                unique.setdefault(key, parameters)
        if len(unique) < batch_size:
            raise ValueError("Random pool has too few unobserved effective candidates")
        start = len(current) if iteration_start is None else iteration_start
        return tuple(_proposal(study, item, start + index, self.backend_id, 0.0,
                               source_observations=items)
                     for index, item in enumerate(list(unique.values())[:batch_size]))


class OptunaTPEOptimizer:
    backend_id = "optuna-motpe-mixed-v1"

    def propose_batch(self, study: OptimizationStudy,
                      observations: Iterable[LearningObservation], *, batch_size: int,
                      baseline_metrics: dict[str, float],
                      historical_observations: Iterable[LearningObservation] = (),
                      excluded_parameters: Iterable[dict[str, Any]] = (),
                      iteration_start: int | None = None,
                      ) -> tuple[OptimizerProposal, ...]:
        del baseline_metrics
        try:
            import optuna
        except ImportError as exc:
            raise RuntimeError("Optuna optimization backend is not installed") from exc
        current = tuple(observations)
        items = _merge_current_and_history(current, historical_observations)
        model_items = tuple(item for item in items
                            if not _observation_is_infrastructure_failure(item))
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        constraints_func = (lambda trial: trial.user_attrs.get(
            "constraint_residuals", (1.0,))) if study.hard_constraints else None
        sampler = optuna.samplers.TPESampler(
            seed=study.seed, multivariate=True, group=True,
            n_startup_trials=max(20, 2 * len(study.parameter_space)),
            constraints_func=constraints_func,
            constant_liar=True,
        )
        directions = ["minimize" if item.direction == "min" else "maximize"
                      for item in study.objectives]
        opt_study = optuna.create_study(directions=directions, sampler=sampler)
        distributions = _optuna_distributions(study.parameter_space, optuna)
        for item in model_items:
            complete = item.status == "succeeded" and all(
                objective.metric_name in item.metrics for objective in study.objectives)
            params = {name: value for name, value in item.parameters.items()
                      if name in distributions}
            dists = {name: distributions[name] for name in params}
            # Import history through Optuna's real lifecycle. ``add_trial``
            # does not invoke TPESampler.constraints_func and silently leaves
            # historical constraints unknown.
            opt_study.enqueue_trial(
                params, user_attrs={"constraint_residuals": list(
                    _constraint_residuals(item, study.hard_constraints))})
            trial = opt_study.ask(fixed_distributions=dists)
            if trial.params != params:
                raise RuntimeError("Optuna history import changed a frozen parameter vector")
            if complete:
                opt_study.tell(trial, values=[float(
                    item.metrics[obj.metric_name]) for obj in study.objectives])
            else:
                opt_study.tell(trial, state=optuna.trial.TrialState.FAIL)
        proposals = []
        encoder = MixedParameterEncoder(study.parameter_space)
        seen = ({_digest(item.parameters) for item in items}
                | {_digest(item) for item in excluded_parameters})
        attempts = 0
        while len(proposals) < batch_size and attempts < batch_size * 64:
            trial = opt_study.ask()
            parameters = {}
            for spec in study.parameter_space:
                if spec.active_when and not all(parameters.get(key) == value
                                                for key, value in spec.active_when.items()):
                    continue
                parameters[spec.name] = _optuna_suggest(trial, spec)
            parameters = encoder.project_relations(parameters)
            key = _digest(parameters); attempts += 1
            if key in seen:
                # Keep the duplicate raw draw pending as a constant-liar point;
                # fabricating a PRUNED multi-objective trial with no values
                # breaks Optuna's Pareto-weight calculation.
                continue
            seen.add(key)
            # The asked trial deliberately remains RUNNING. TPESampler's real
            # constant-liar mode accounts for pending points without inventing
            # objective or feasibility observations.
            start = len(current) if iteration_start is None else iteration_start
            proposals.append(_proposal(
                study, parameters, start + len(proposals), self.backend_id, 0.0,
                source_observations=items,
                model_metadata={
                    "backend_id": self.backend_id,
                    "constraint_handling": (
                        "Optuna TPESampler constraints_func; residual <= 0 is feasible"
                        if study.hard_constraints else "no hard constraints"),
                    "parallel_batch_policy": (
                        "Optuna constant_liar=True; pending trials remain RUNNING"),
                    "infrastructure_failures_excluded_from_model": sum(
                        _observation_is_infrastructure_failure(item)
                        for item in items),
                },
            ))
        if len(proposals) < batch_size:
            raise ValueError("TPE could not produce a unique effective batch")
        return tuple(proposals)


class BoTorchQNEHVIOptimizer:
    """Constrained noisy-EHVI over a deduplicated mixed discrete candidate pool."""

    backend_id = "botorch-ard-matern-qlognehvi-mixed-v2"

    def __init__(self, *, pool_size: int = 4096, minimum_initial: int | None = None,
                 forbidden_configuration_ids: Iterable[str] = (),
                 trust_region_center: dict[str, Any] | None = None,
                 trust_region_radius: float | None = None,
                 trust_region_stage_focus: str | None = None,
                 use_feasibility_model: bool = True,
                 use_safe_initialization: bool = True,
                 minimum_anchor_replicas: int = 2,
                 backend_id_override: str | None = None):
        if not 256 <= pool_size <= 65_536:
            raise ValueError("pool_size must be between 256 and 65536")
        self.pool_size = pool_size
        self.minimum_initial = minimum_initial
        self.forbidden_configuration_ids = frozenset(forbidden_configuration_ids)
        self.trust_region_center = trust_region_center
        self.trust_region_radius = trust_region_radius
        self.trust_region_stage_focus = trust_region_stage_focus
        self.use_feasibility_model = bool(use_feasibility_model)
        self.use_safe_initialization = bool(use_safe_initialization)
        if not 2 <= minimum_anchor_replicas <= 8:
            raise ValueError("minimum_anchor_replicas must be between 2 and 8")
        self.minimum_anchor_replicas = int(minimum_anchor_replicas)
        self.proposal_backend_id = backend_id_override or self.backend_id
        if (trust_region_center is None) != (trust_region_radius is None):
            raise ValueError("trust-region center and radius must be provided together")
        if trust_region_radius is not None and not .01 <= trust_region_radius <= 1:
            raise ValueError("trust-region radius must be between .01 and 1")

    def propose_batch(self, study: OptimizationStudy,
                      observations: Iterable[LearningObservation], *, batch_size: int,
                      baseline_metrics: dict[str, float],
                      historical_observations: Iterable[LearningObservation] = (),
                      excluded_parameters: Iterable[dict[str, Any]] = (),
                      iteration_start: int | None = None,
                      ) -> tuple[OptimizerProposal, ...]:
        study.validate()
        if not 1 <= batch_size <= 32:
            raise ValueError("batch_size must be between 1 and 32")
        current = tuple(observations)
        items = _merge_current_and_history(current, historical_observations)
        model_items = tuple(item for item in items
                            if not _observation_is_infrastructure_failure(item))
        encoder = MixedParameterEncoder(study.parameter_space)
        initial = self.minimum_initial or max(32, 4 * len(study.parameter_space))
        # Infrastructure failures still consume the frozen logical budget and
        # remain in ``items`` for deduplication/audit, but they must not teach
        # the surrogate that a parameter vector is physically infeasible.
        unique_observed = len({_digest(item.parameters) for item in model_items})
        if unique_observed < initial:
            initializer: OptimizerBackend = (SafeAnchoredSobolOptimizer(
                forbidden_configuration_ids=self.forbidden_configuration_ids,
                minimum_anchor_replicas=self.minimum_anchor_replicas,
            ) if self.use_safe_initialization else SobolOptimizer(
                forbidden_configuration_ids=self.forbidden_configuration_ids,
            ))
            return initializer.propose_batch(
                study, items, batch_size=batch_size, baseline_metrics=baseline_metrics,
                excluded_parameters=excluded_parameters,
                iteration_start=iteration_start,
            )
        missing = [obj.metric_name for obj in study.objectives if obj.metric_name not in baseline_metrics]
        if missing:
            raise ValueError(f"Baseline metrics missing objectives: {', '.join(missing)}")

        try:
            import torch
            from botorch.acquisition.multi_objective.logei import (
                qLogNoisyExpectedHypervolumeImprovement,
            )
            from botorch.acquisition.multi_objective.objective import IdentityMCMultiOutputObjective
            from botorch.fit import fit_gpytorch_mll
            from botorch.models import ModelListGP, SingleTaskGP
            from botorch.models.transforms.outcome import Standardize
            from botorch.optim import optimize_acqf_discrete
            from gpytorch.kernels import MaternKernel, ScaleKernel
            from gpytorch.mlls.sum_marginal_log_likelihood import SumMarginalLogLikelihood
        except ImportError as exc:
            raise RuntimeError("BoTorch optimization backend is not installed") from exc

        grouped: dict[str, list[LearningObservation]] = {}
        for item in model_items:
            grouped.setdefault(_digest(item.parameters), []).append(item)
        group_rows = list(grouped.values())
        all_x = torch.tensor(np.stack([encoder.encode(group[0].parameters)
                                      for group in group_rows]), dtype=torch.double)
        successful_indexes, objective_rows, objective_variances = [], [], []
        constraint_rows, constraint_variances = [], []
        for group_index, group in enumerate(group_rows):
            complete = [item for item in group if item.status == "succeeded" and all(
                objective.metric_name in item.metrics for objective in study.objectives)]
            # Model each signed hard-constraint residual directly instead of
            # collapsing timing, DRC and process failures into one empirical
            # pass-rate scalar.  This preserves *why* a point is infeasible
            # and lets qLogNEHVI prefer a likely timing/DRC recovery region.
            residual_matrix = np.asarray([
                _constraint_residuals(item, study.hard_constraints)
                for item in group
            ], dtype=float)
            if study.hard_constraints:
                constraint_rows.append(np.mean(residual_matrix, axis=0).tolist())
                constraint_variances.append(np.maximum(
                    np.var(residual_matrix, axis=0, ddof=1) / len(group)
                    if len(group) > 1 else np.full(len(study.hard_constraints), 1e-4),
                    1e-4,
                ).tolist())
            if not complete:
                continue
            successful_indexes.append(group_index); row = []; variance_row = []
            for objective in study.objectives:
                baseline = float(baseline_metrics[objective.metric_name])
                scale = float(objective.normalization_scale or max(abs(baseline), 1e-12))
                objective_weight = float(objective.weight) / sum(
                    float(item.weight) for item in study.objectives)
                gains = []
                for item in complete:
                    measured = float(item.metrics[objective.metric_name])
                    gain = ((measured - baseline) / scale if objective.direction == "max"
                            else (baseline - measured) / scale)
                    gains.append(gain * objective_weight)
                row.append(float(np.mean(gains)))
                variance_row.append(float(np.var(gains, ddof=1) / len(gains))
                                    if len(gains) > 1 else 1e-6)
            objective_rows.append(row); objective_variances.append(variance_row)
        if len(successful_indexes) < 2:
            initializer: OptimizerBackend = (SafeAnchoredSobolOptimizer(
                forbidden_configuration_ids=self.forbidden_configuration_ids,
                minimum_anchor_replicas=self.minimum_anchor_replicas,
            ) if self.use_safe_initialization else SobolOptimizer(
                forbidden_configuration_ids=self.forbidden_configuration_ids,
            ))
            return initializer.propose_batch(
                study, items, batch_size=batch_size, baseline_metrics=baseline_metrics,
                excluded_parameters=excluded_parameters,
                iteration_start=iteration_start,
            )
        objective_x = all_x[successful_indexes]
        train_y = torch.tensor(np.asarray(objective_rows), dtype=torch.double)
        train_yvar = torch.tensor(
            np.asarray(objective_variances), dtype=torch.double).clamp_min(1e-5)
        models = [SingleTaskGP(
                    objective_x, train_y[:, index:index + 1],
                    train_Yvar=train_yvar[:, index:index + 1],
                    covar_module=ScaleKernel(MaternKernel(
                        nu=2.5, ard_num_dims=encoder.encoded_dimension)),
                    outcome_transform=Standardize(m=1))
                  for index in range(train_y.shape[1])]
        constraint_model_count = 0
        if self.use_feasibility_model and study.hard_constraints:
            constraint_y = torch.tensor(np.asarray(constraint_rows), dtype=torch.double)
            constraint_yvar = torch.tensor(
                np.asarray(constraint_variances), dtype=torch.double).clamp_min(1e-5)
            constraint_model_count = constraint_y.shape[1]
            models.extend(SingleTaskGP(
                all_x, constraint_y[:, index:index + 1],
                train_Yvar=constraint_yvar[:, index:index + 1],
                covar_module=ScaleKernel(MaternKernel(
                    nu=2.5, ard_num_dims=encoder.encoded_dimension)),
                outcome_transform=Standardize(m=1))
                for index in range(constraint_model_count))
        model = ModelListGP(*models)
        fit_gpytorch_mll(SumMarginalLogLikelihood(model.likelihood, model))

        seen = ({_digest(item.parameters) for item in items}
                | {_digest(item) for item in excluded_parameters})
        pool_builder = (encoder.sobol_candidates if self.trust_region_center is None
                        else lambda count, seed: encoder.trust_region_candidates(
                            count, seed=seed, center=self.trust_region_center or {},
                            radius=float(self.trust_region_radius),
                            stage_focus=self.trust_region_stage_focus))
        pool_parameters = [item for item in pool_builder(
            self.pool_size, seed=study.seed + len(items) * 1009,
        ) if _digest(item) not in seen and _digest(item) not in self.forbidden_configuration_ids]
        if len(pool_parameters) < batch_size:
            raise ValueError("Candidate pool has too few unobserved effective configurations")
        choices = torch.tensor(np.stack([encoder.encode(item) for item in pool_parameters]),
                               dtype=torch.double)
        objective_count = len(study.objectives)
        # Relative gains use a fixed baseline, so -1 is a stable, auditable
        # reference rather than a moving min/max normalization.
        acquisition = qLogNoisyExpectedHypervolumeImprovement(
            model=model, ref_point=[-1.0] * objective_count,
            X_baseline=all_x,
            objective=IdentityMCMultiOutputObjective(outcomes=list(range(objective_count))),
            constraints=([
                (lambda samples, index=index: samples[..., objective_count + index])
                for index in range(constraint_model_count)
            ] if constraint_model_count else None),
            prune_baseline=True,
        )
        selected, values = optimize_acqf_discrete(
            acquisition, q=batch_size, choices=choices, unique=True,
        )
        proposals = []
        joint_log_value = float(values.reshape(-1)[0].item())
        joint_value = float(math.exp(max(-745.0, min(700.0, joint_log_value))))
        start = len(current) if iteration_start is None else iteration_start
        model_id = f"botorch-qnehvi-{_digest({'study': study.study_id, 'n': len(group_rows), 'seed': study.seed})[:16]}"
        ard_lengthscales = {}
        for objective, fitted in zip(study.objectives, models[:objective_count]):
            kernel = getattr(fitted.covar_module, "base_kernel", fitted.covar_module)
            raw = kernel.lengthscale.detach().cpu().reshape(-1).tolist()
            ard_lengthscales[objective.metric_name] = [float(item) for item in raw]
        model_metadata = {
            "backend_id": self.proposal_backend_id, "has_fitted_surrogate": True,
            "model_id": model_id, "surrogate": "independent SingleTaskGP",
            "kernel": "ARD Matern-5/2 over normalized numeric/one-hot encoding",
            "acquisition": ("constrained qLogNEHVI" if constraint_model_count
                            else "unconstrained qLogNEHVI"),
            "log_acquisition_value": joint_log_value,
            "hard_constraints": list(study.hard_constraints),
            "feasibility_model_enabled": self.use_feasibility_model,
            "feasibility_representation": (
                "one signed GP residual per hard constraint; residual <= 0 is feasible"
                if constraint_model_count else "disabled or no hard constraints"),
            "constraint_model_count": constraint_model_count,
            "unique_training_configurations": len(group_rows),
            "successful_training_configurations": len(successful_indexes),
            "failed_or_incomplete_configurations": (
                len(group_rows) - len(successful_indexes)),
            "infrastructure_failures_excluded_from_model": sum(
                _observation_is_infrastructure_failure(item) for item in items),
            "ard_lengthscales": ard_lengthscales,
            "normalization": "fixed baseline-relative weighted gain",
            "trust_region": ({"center": self.trust_region_center,
                               "radius": self.trust_region_radius,
                               "stage_focus": self.trust_region_stage_focus}
                              if self.trust_region_center is not None else None),
        }
        total_weight = sum(float(item.weight) for item in study.objectives)
        for index, encoded in enumerate(selected):
            distances = torch.sum((choices - encoded) ** 2, dim=1)
            pool_index = int(torch.argmin(distances).item())
            prediction_values = []
            prediction_x = encoded.reshape(1, -1)
            for objective_index, objective in enumerate(study.objectives):
                posterior = models[objective_index].posterior(prediction_x)
                weighted_gain = float(posterior.mean.reshape(-1)[0].item())
                weighted_std = float(posterior.variance.clamp_min(0).sqrt().reshape(-1)[0].item())
                weight_fraction = float(objective.weight) / total_weight
                scale = float(objective.normalization_scale or max(
                    abs(float(baseline_metrics[objective.metric_name])), 1e-12))
                gain = weighted_gain / weight_fraction
                metric_std = weighted_std * scale / weight_fraction
                baseline = float(baseline_metrics[objective.metric_name])
                metric_mean = (baseline + gain * scale
                               if objective.direction == "max"
                               else baseline - gain * scale)
                prediction_values.append((objective.metric_name, metric_mean,
                                          metric_std, model_id))
            proposals.append(_proposal(
                study, pool_parameters[pool_index], start + index,
                self.proposal_backend_id, joint_value, source_observations=items,
                prediction_values=prediction_values,
                model_metadata=model_metadata,
            ))
        return tuple(proposals)


def _configuration_scores(study: OptimizationStudy,
                          observations: Sequence[LearningObservation],
                          baseline_metrics: dict[str, float], *,
                          minimum_replicas: int = 2) \
        -> list[tuple[dict[str, Any], float]]:
    grouped: dict[str, list[LearningObservation]] = {}
    order = []
    for item in observations:
        key = _digest(item.parameters)
        if key not in grouped:
            order.append(key)
        grouped.setdefault(key, []).append(item)
    total_weight = sum(float(item.weight) for item in study.objectives)
    scored = []
    for key in order:
        replicas = [item for item in grouped[key]
                    if item.context.flow_stage == "finish"
                    and not _observation_is_infrastructure_failure(item)]
        if (len(replicas) < minimum_replicas
                or not all(_observation_is_feasible(
                    item, study.hard_constraints) for item in replicas)
                or not all(all(objective.metric_name in item.metrics
                               for objective in study.objectives)
                           for item in replicas)):
            continue
        score = 0.0
        for objective in study.objectives:
            measured = float(np.median([
                item.metrics[objective.metric_name] for item in replicas]))
            baseline = float(baseline_metrics[objective.metric_name])
            scale = float(objective.normalization_scale or max(abs(baseline), 1e-12))
            gain = ((measured - baseline) / scale if objective.direction == "max"
                    else (baseline - measured) / scale)
            score += float(objective.weight) / total_weight * gain
        scored.append((grouped[key][0].parameters, float(score)))
    return scored


class AdaptiveTrustRegionQNEHVIOptimizer:
    """TuRBO-style local qNEHVI with an observation-derived trust region.

    This is deliberately named "TuRBO-style" rather than claiming the exact
    reference implementation: mixed discrete projection and multi-objective
    qNEHVI are platform-specific extensions, while radius contraction follows
    the same success/failure trust-region principle.
    """

    backend_id = "adaptive-trust-region-qlognehvi-mixed-v2"

    def __init__(self, *, pool_size: int = 4096, minimum_initial: int | None = None,
                 forbidden_configuration_ids: Iterable[str] = (),
                 stage_focus: str | None = None,
                 use_feasibility_model: bool = True,
                 use_safe_initialization: bool = True,
                 minimum_anchor_replicas: int = 2):
        self.pool_size = pool_size
        self.minimum_initial = minimum_initial
        self.forbidden_configuration_ids = tuple(forbidden_configuration_ids)
        self.stage_focus = stage_focus
        self.use_feasibility_model = bool(use_feasibility_model)
        self.use_safe_initialization = bool(use_safe_initialization)
        self.minimum_anchor_replicas = int(minimum_anchor_replicas)

    def propose_batch(self, study: OptimizationStudy,
                      observations: Iterable[LearningObservation], *, batch_size: int,
                      baseline_metrics: dict[str, float],
                      historical_observations: Iterable[LearningObservation] = (),
                      excluded_parameters: Iterable[dict[str, Any]] = (),
                      iteration_start: int | None = None,
                      ) -> tuple[OptimizerProposal, ...]:
        current = tuple(observations)
        historical = tuple(historical_observations)
        items = _merge_current_and_history(current, historical)
        scores = _configuration_scores(
            study, items, baseline_metrics,
            minimum_replicas=self.minimum_anchor_replicas)
        initial = self.minimum_initial or max(32, 4 * len(study.parameter_space))
        if len(scores) < initial:
            return BoTorchQNEHVIOptimizer(
                pool_size=self.pool_size, minimum_initial=initial,
                forbidden_configuration_ids=self.forbidden_configuration_ids,
                use_feasibility_model=self.use_feasibility_model,
                use_safe_initialization=self.use_safe_initialization,
                minimum_anchor_replicas=self.minimum_anchor_replicas,
            ).propose_batch(
                study, current, batch_size=batch_size,
                baseline_metrics=baseline_metrics,
                historical_observations=historical,
                excluded_parameters=excluded_parameters,
                iteration_start=iteration_start,
            )
        center, _ = max(scores, key=lambda item: item[1])
        best = -math.inf
        consecutive_failures = 0
        consecutive_successes = 0
        for _, score in scores:
            if score > best + .005:
                best = score
                consecutive_successes += 1
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                consecutive_successes = 0
        radius = .50
        radius *= 2 ** (consecutive_successes // 3)
        radius *= .5 ** (consecutive_failures // 3)
        radius = min(1.0, max(.05, radius))
        return BoTorchQNEHVIOptimizer(
            pool_size=self.pool_size, minimum_initial=initial,
            forbidden_configuration_ids=self.forbidden_configuration_ids,
            trust_region_center=center, trust_region_radius=radius,
            trust_region_stage_focus=self.stage_focus,
            use_feasibility_model=self.use_feasibility_model,
            use_safe_initialization=self.use_safe_initialization,
            minimum_anchor_replicas=self.minimum_anchor_replicas,
            backend_id_override=self.backend_id,
        ).propose_batch(
            study, current, batch_size=batch_size,
            baseline_metrics=baseline_metrics,
            historical_observations=historical,
            excluded_parameters=excluded_parameters,
            iteration_start=iteration_start,
        )


class IndustrialOptimizerPortfolio:
    """Auditable routing across initialization, robust mixed, global, and local BO."""

    backend_id = "industrial-dse-portfolio-v1"

    def __init__(self, *, minimum_initial: int | None = None,
                 forbidden_configuration_ids: Iterable[str] = (),
                 routing_hints: Iterable[dict[str, Any]] = (),
                 use_feasibility_model: bool = True,
                 use_safe_initialization: bool = True,
                 minimum_anchor_replicas: int = 2,
                 use_trust_region: bool = True,
                 use_stage_focus: bool = True):
        self.minimum_initial = minimum_initial
        self.forbidden_configuration_ids = tuple(forbidden_configuration_ids)
        self.routing_hints = tuple(routing_hints)
        self.use_feasibility_model = bool(use_feasibility_model)
        self.use_safe_initialization = bool(use_safe_initialization)
        self.minimum_anchor_replicas = int(minimum_anchor_replicas)
        self.use_trust_region = bool(use_trust_region)
        self.use_stage_focus = bool(use_stage_focus)

    def propose_batch(self, study: OptimizationStudy,
                      observations: Iterable[LearningObservation], *, batch_size: int,
                      baseline_metrics: dict[str, float],
                      historical_observations: Iterable[LearningObservation] = (),
                      excluded_parameters: Iterable[dict[str, Any]] = (),
                      iteration_start: int | None = None,
                      ) -> tuple[OptimizerProposal, ...]:
        current = tuple(observations)
        historical = tuple(historical_observations)
        items = _merge_current_and_history(current, historical)
        model_items = tuple(item for item in items
                            if not _observation_is_infrastructure_failure(item))
        unique = len({_digest(item.parameters) for item in model_items})
        initial = self.minimum_initial or max(32, 4 * len(study.parameter_space))
        failures = sum(item.status != "succeeded" for item in model_items)
        failure_rate = failures / len(model_items) if model_items else 0.0
        scores = _configuration_scores(
            study, model_items, baseline_metrics,
            minimum_replicas=self.minimum_anchor_replicas)
        stage_by_parameter = {item.name: item.stage for item in study.parameter_space}
        stage_votes: dict[str, int] = {}
        hint_fingerprints = []
        for hint in self.routing_hints:
            if hint.get("status") != "active":
                continue
            hint_fingerprints.append(str(hint.get("fingerprint") or ""))
            payload = hint.get("payload") or {}
            names = ([payload.get("parameter")] if payload.get("parameter") else
                     payload.get("parameters") or [])
            for name in names:
                stage = stage_by_parameter.get(name)
                if stage:
                    stage_votes[stage] = stage_votes.get(stage, 0) + 1
        stage_focus = (max(stage_votes, key=lambda stage: (stage_votes[stage], stage))
                       if stage_votes and self.use_stage_focus else None)
        best = -math.inf
        stalls = 0
        for _, score in scores:
            if score > best + .005:
                best = score; stalls = 0
            else:
                stalls += 1
        if unique < initial:
            if self.use_safe_initialization:
                route = "cold_start_safe_anchored_space_filling"
                backend: OptimizerBackend = SafeAnchoredSobolOptimizer(
                    forbidden_configuration_ids=self.forbidden_configuration_ids,
                    minimum_anchor_replicas=self.minimum_anchor_replicas)
            else:
                route = "cold_start_global_sobol_no_safe_anchor"
                backend = SobolOptimizer(
                    forbidden_configuration_ids=self.forbidden_configuration_ids)
        elif failure_rate > .25:
            route = "failure_robust_mixed_density"
            backend = OptunaTPEOptimizer()
        elif stalls >= 3 and self.use_trust_region:
            route = "stalled_local_trust_region"
            backend = AdaptiveTrustRegionQNEHVIOptimizer(
                minimum_initial=initial,
                forbidden_configuration_ids=self.forbidden_configuration_ids,
                stage_focus=stage_focus,
                use_feasibility_model=self.use_feasibility_model,
                use_safe_initialization=self.use_safe_initialization,
                minimum_anchor_replicas=self.minimum_anchor_replicas)
        else:
            route = ("stalled_global_multiobjective_no_trust_region"
                     if stalls >= 3 else "global_constrained_multiobjective")
            backend = BoTorchQNEHVIOptimizer(
                minimum_initial=initial,
                forbidden_configuration_ids=self.forbidden_configuration_ids,
                use_feasibility_model=self.use_feasibility_model,
                use_safe_initialization=self.use_safe_initialization,
                minimum_anchor_replicas=self.minimum_anchor_replicas)
        proposals = backend.propose_batch(
            study, current, batch_size=batch_size,
            baseline_metrics=baseline_metrics,
            historical_observations=historical,
            excluded_parameters=excluded_parameters,
            iteration_start=iteration_start,
        )
        return tuple(replace(
            proposal,
            model_metadata={
                **proposal.model_metadata,
                "portfolio_backend_id": self.backend_id,
                "portfolio_route": route,
                "route_evidence": {
                    "unique_configurations": unique,
                    "minimum_initial": initial,
                    "observation_failure_rate": failure_rate,
                    "infrastructure_failures_excluded_from_routing": sum(
                        _observation_is_infrastructure_failure(item) for item in items),
                    "consecutive_nonimproving_configurations": stalls,
                    "stage_focus": stage_focus,
                    "feasibility_model_enabled": self.use_feasibility_model,
                    "safe_initialization_enabled": self.use_safe_initialization,
                    "trust_region_enabled": self.use_trust_region,
                    "stage_focus_enabled": self.use_stage_focus,
                    "active_memory_artifact_fingerprints": hint_fingerprints,
                },
            },
        ) for proposal in proposals)


class OptimizerRegistry:
    def __init__(self, backends: Iterable[OptimizerBackend] = ()):
        self._backends = {item.backend_id: item for item in backends}

    def register(self, backend: OptimizerBackend) -> None:
        if backend.backend_id in self._backends:
            raise ValueError(f"Optimizer backend already registered: {backend.backend_id}")
        self._backends[backend.backend_id] = backend

    def resolve(self, backend_id: str) -> OptimizerBackend:
        try:
            return self._backends[backend_id]
        except KeyError as exc:
            raise KeyError(f"Unknown optimizer backend: {backend_id}") from exc


def default_optimizer_registry() -> OptimizerRegistry:
    return OptimizerRegistry((RandomOptimizer(), SobolOptimizer(),
                              SafeAnchoredSobolOptimizer(), OptunaTPEOptimizer(),
                              BoTorchQNEHVIOptimizer(),
                              AdaptiveTrustRegionQNEHVIOptimizer(),
                              IndustrialOptimizerPortfolio()))


def _optuna_distributions(specs: Sequence[ParameterSpec], optuna) -> dict[str, Any]:
    result = {}
    for spec in specs:
        if spec.kind == "categorical":
            result[spec.name] = optuna.distributions.CategoricalDistribution(spec.choices)
        elif spec.kind == "bool":
            result[spec.name] = optuna.distributions.CategoricalDistribution((0, 1))
        elif spec.kind == "int":
            result[spec.name] = optuna.distributions.IntDistribution(
                int(spec.lower), int(spec.upper), step=int(spec.step or 1))
        else:
            result[spec.name] = optuna.distributions.FloatDistribution(
                float(spec.lower), float(spec.upper), step=spec.step)
    return result


def _optuna_suggest(trial, spec: ParameterSpec) -> Any:
    if spec.kind == "categorical":
        return trial.suggest_categorical(spec.name, spec.choices)
    if spec.kind == "bool":
        return trial.suggest_categorical(spec.name, (0, 1))
    if spec.kind == "int":
        return trial.suggest_int(spec.name, int(spec.lower), int(spec.upper),
                                 step=int(spec.step or 1))
    return trial.suggest_float(spec.name, float(spec.lower), float(spec.upper), step=spec.step)


def _proposal(study: OptimizationStudy, parameters: dict[str, Any], iteration: int,
              backend_id: str, acquisition: float, *,
              source_observations: Iterable[LearningObservation] = (),
              prediction_values: Sequence[tuple[str, float, float, str]] = (),
              model_metadata: dict[str, Any] | None = None,
              ) -> OptimizerProposal:
    candidate_id = f"candidate-{_digest({'study': study.study_id, 'parameters': parameters})[:20]}"
    evidence = [EvidencePointer(ref=f"source:study:{study.study_id}",
                                sha256=_digest(study.to_dict()))]
    # Proposals remain non-executable data, but retain the immutable evidence
    # lineage that actually informed the model (including exact-context warm
    # starts). Deduplicate shared run/result pointers without weakening them to
    # a mutable database query.
    seen_evidence = {(evidence[0].ref, evidence[0].sha256)}
    for observation in source_observations:
        for pointer in observation.evidence:
            key = (pointer.ref, pointer.sha256)
            if key not in seen_evidence:
                evidence.append(pointer)
                seen_evidence.add(key)
    predictions = tuple(Prediction(
        prediction_id=f"prediction-{_digest({'candidate': candidate_id, 'metric': metric, 'model': model_id})[:20]}",
        study_id=study.study_id, candidate_id=candidate_id,
        metric_name=metric, mean=float(mean), stddev=max(0.0, float(stddev)),
        model_id=model_id, context_fingerprint=study.context_fingerprint,
    ) for metric, mean, stddev, model_id in prediction_values)
    proposal = OptimizerProposal(
        proposal_id=f"optimizer-{_digest({'candidate': candidate_id, 'iteration': iteration})[:20]}",
        study_id=study.study_id, candidate_id=candidate_id, iteration=iteration,
        parameters=parameters, predictions=predictions,
        acquisition_value=float(acquisition), evidence=tuple(evidence),
        model_metadata=model_metadata or {"backend_id": backend_id,
                                          "has_fitted_surrogate": False},
    )
    proposal.validate()
    return proposal
