"""Evidence-gated persistent state for physical-design optimization."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any, Callable, Iterable

import numpy as np

from openroad_platform_contracts import LearningObservation, ObjectiveSpec


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _discovery_holdout(items: list[dict[str, Any]], minimum_holdout: int) \
        -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ordered = sorted(items, key=lambda item: item["configuration_id"])
    if len(ordered) < 6:
        return ordered, []
    holdout_count = min(max(minimum_holdout, math.ceil(len(ordered) * .25)),
                        len(ordered) - 3)
    return ordered[:-holdout_count], ordered[-holdout_count:]


def _spearman(items: list[dict[str, Any]], parameter: str,
              metric: str) -> float | None:
    if len(items) < 3:
        return None
    from scipy.stats import spearmanr
    x = np.asarray([float(item["parameters"][parameter]) for item in items])
    y = np.asarray([float(item["metrics"][metric]) for item in items])
    if len(set(x)) < 2 or len(set(y)) < 2:
        return None
    value = float(spearmanr(x, y).statistic)
    return value if math.isfinite(value) else None


def _interaction_effect(items: list[dict[str, Any]], first: str,
                        second: str, metric: str) -> float | None:
    if len(items) < 4:
        return None
    first_values = np.asarray([
        float(item["parameters"][first]) for item in items], dtype=float)
    second_values = np.asarray([
        float(item["parameters"][second]) for item in items], dtype=float)
    target = np.asarray([float(item["metrics"][metric]) for item in items], dtype=float)
    if min(np.std(first_values), np.std(second_values), np.std(target)) <= 1e-12:
        return None
    x1 = (first_values - np.mean(first_values)) / np.std(first_values)
    x2 = (second_values - np.mean(second_values)) / np.std(second_values)
    y = (target - np.mean(target)) / np.std(target)
    matrix = np.column_stack((np.ones(len(items)), x1, x2, x1 * x2))
    coefficient = float(np.linalg.lstsq(matrix, y, rcond=None)[0][-1])
    return coefficient if math.isfinite(coefficient) else None


@dataclass(frozen=True)
class MemoryPolicy:
    minimum_corroborating_configurations: int = 12
    minimum_absolute_spearman: float = .30
    minimum_holdout_configurations: int = 4
    minimum_standardized_interaction: float = .15

    def validate(self) -> None:
        if not 3 <= self.minimum_corroborating_configurations <= 10_000:
            raise ValueError("minimum corroboration must be between 3 and 10000")
        if not 0 < self.minimum_absolute_spearman <= 1:
            raise ValueError("minimum absolute Spearman must be in (0,1]")
        if not 3 <= self.minimum_holdout_configurations <= 1000:
            raise ValueError("minimum holdout configurations must be between 3 and 1000")
        if not 0 < self.minimum_standardized_interaction <= 2:
            raise ValueError("minimum standardized interaction must be in (0,2]")


class PersistentOptimizationMemory:
    """Append-only observations plus reproducibly rebuilt typed artifacts."""

    def __init__(self, path: str | Path, policy: MemoryPolicy = MemoryPolicy(), *,
                 evidence_verifier: Callable[[LearningObservation], bool] | None = None):
        policy.validate(); self.policy = policy
        self.evidence_verifier = evidence_verifier
        self.path = Path(path).expanduser().resolve(); self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS optimization_memory_observations_v1 (
                    observation_id TEXT PRIMARY KEY, context_fingerprint TEXT NOT NULL,
                    design_id TEXT NOT NULL, platform TEXT NOT NULL, pdk_id TEXT NOT NULL,
                    toolchain_id TEXT NOT NULL, effective_configuration_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL, fingerprint TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_optimization_memory_context
                  ON optimization_memory_observations_v1(context_fingerprint, created_at);
                CREATE TABLE IF NOT EXISTS optimization_memory_artifacts_v1 (
                    artifact_id TEXT PRIMARY KEY, context_fingerprint TEXT NOT NULL,
                    kind TEXT NOT NULL, status TEXT NOT NULL,
                    support_count INTEGER NOT NULL, contradiction_count INTEGER NOT NULL,
                    payload_json TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    rebuilt_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(context_fingerprint, kind, fingerprint)
                );
                CREATE TABLE IF NOT EXISTS optimization_memory_transfer_v1 (
                    transfer_id TEXT PRIMARY KEY, source_context_fingerprint TEXT NOT NULL,
                    target_context_fingerprint TEXT NOT NULL,
                    source_artifact_fingerprint TEXT NOT NULL, kind TEXT NOT NULL,
                    status TEXT NOT NULL, payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(target_context_fingerprint, source_artifact_fingerprint)
                );
            """)

    def ingest(self, observation: LearningObservation,
               objectives: Iterable[ObjectiveSpec]) -> dict[str, Any]:
        observation.validate(); objective_items = tuple(objectives)
        if not observation.evidence:
            raise ValueError("Optimization memory requires immutable evidence")
        run_pointer = next((item for item in observation.evidence
                            if item.ref == f"run:{observation.run_id}"), None)
        if run_pointer is None:
            raise ValueError("Optimization memory requires an exact Runtime run pointer")
        if self.evidence_verifier is not None and not self.evidence_verifier(observation):
            raise ValueError("Optimization memory evidence failed Runtime verification")
        configuration_id = _digest(observation.parameters)
        payload = observation.to_dict()
        with self._connect() as connection:
            try:
                connection.execute(
                    """INSERT INTO optimization_memory_observations_v1
                       (observation_id,context_fingerprint,design_id,platform,pdk_id,toolchain_id,
                        effective_configuration_id,payload_json,fingerprint)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (observation.observation_id, observation.context.fingerprint,
                     observation.context.design_id, observation.context.platform,
                     observation.context.pdk_id, observation.context.toolchain_id,
                     configuration_id, json.dumps(payload), observation.fingerprint),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT fingerprint FROM optimization_memory_observations_v1 WHERE observation_id=?",
                    (observation.observation_id,)).fetchone()
                if row is None or row["fingerprint"] != observation.fingerprint:
                    raise ValueError("Optimization memory observation identity conflicts")
        return self.rebuild(observation.context.fingerprint, objective_items)

    def observations(self, context_fingerprint: str) -> list[LearningObservation]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM optimization_memory_observations_v1 WHERE context_fingerprint=? ORDER BY created_at,observation_id",
                (context_fingerprint,)).fetchall()
        return [LearningObservation.from_dict(json.loads(row["payload_json"])) for row in rows]

    def rebuild(self, context_fingerprint: str,
                objectives: Iterable[ObjectiveSpec]) -> dict[str, Any]:
        objective_items = tuple(objectives); observations = self.observations(context_fingerprint)
        grouped: dict[str, list[LearningObservation]] = {}
        for item in observations:
            grouped.setdefault(_digest(item.parameters), []).append(item)
        summaries = []
        for configuration_id, replicas in grouped.items():
            complete = [item for item in replicas if item.status == "succeeded"]
            metrics = {}
            for objective in objective_items:
                values = [float(item.metrics[objective.metric_name]) for item in complete
                          if objective.metric_name in item.metrics]
                if values: metrics[objective.metric_name] = float(median(values))
            summaries.append({
                "configuration_id": configuration_id,
                "parameters": replicas[0].parameters,
                "replicas": len(replicas), "successes": len(complete),
                "feasibility": len(complete) / len(replicas), "metrics": metrics,
                "runtime_median_seconds": float(median(item.cost_seconds for item in replicas)),
                "evidence_refs": [pointer.to_dict() for item in replicas for pointer in item.evidence[:1]],
            })
        artifacts = self._derive_artifacts(context_fingerprint, summaries, objective_items)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM optimization_memory_artifacts_v1 WHERE context_fingerprint=?",
                               (context_fingerprint,))
            for artifact in artifacts:
                fingerprint = _digest(artifact["payload"])
                artifact_id = f"memory-{_digest({'context': context_fingerprint, 'fingerprint': fingerprint})[:24]}"
                connection.execute(
                    "INSERT INTO optimization_memory_artifacts_v1 VALUES (?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
                    (artifact_id, context_fingerprint, artifact["kind"],
                     artifact["status"], artifact["support_count"],
                     artifact["contradiction_count"], json.dumps(artifact["payload"]), fingerprint),
                )
        return self.snapshot(context_fingerprint)

    def _derive_artifacts(self, context_fingerprint: str, summaries: list[dict[str, Any]],
                          objectives: tuple[ObjectiveSpec, ...]) -> list[dict[str, Any]]:
        artifacts = []
        unique_count = len(summaries); threshold = self.policy.minimum_corroborating_configurations
        runtime_values = [item["runtime_median_seconds"] for item in summaries]
        if runtime_values:
            artifacts.append({"kind": "runtime_model", "status": "active",
                              "support_count": unique_count, "contradiction_count": 0,
                              "payload": {"context_fingerprint": context_fingerprint,
                                          "median_seconds": float(median(runtime_values)),
                                          "configuration_count": unique_count}})
        failures = [item for item in summaries if item["successes"] < item["replicas"]]
        for item in failures:
            failed_replicas = item["replicas"] - item["successes"]
            status = ("retired" if item["successes"] > 0 and failed_replicas >= threshold
                      else "active" if failed_replicas >= threshold
                      and item["successes"] == 0 else "candidate")
            artifacts.append({"kind": "failure_region", "status": status,
                              "support_count": failed_replicas,
                              "contradiction_count": item["successes"],
                              "payload": {"configuration_id": item["configuration_id"],
                                          "parameters": item["parameters"],
                                          "evidence_refs": item["evidence_refs"],
                                          "scope": "exact effective configuration only",
                                          "retirement_reason": (
                                              "a successful exact-configuration replay contradicts the failure rule"
                                              if status == "retired" else None)}})
        complete = [item for item in summaries if all(
            objective.metric_name in item["metrics"] for objective in objectives)]
        if len(complete) >= 3:
            from scipy.stats import spearmanr
            names = sorted(set.intersection(*(set(item["parameters"]) for item in complete)))
            discovery, holdout = _discovery_holdout(
                complete, self.policy.minimum_holdout_configurations)
            for name in names:
                if any(isinstance(item["parameters"][name], (str, bool))
                       for item in complete):
                    continue
                x = np.asarray([float(item["parameters"][name]) for item in complete])
                if len(set(x)) < 3:
                    continue
                for objective in objectives:
                    discovery_correlation = _spearman(
                        discovery, name, objective.metric_name)
                    holdout_correlation = _spearman(
                        holdout, name, objective.metric_name)
                    correlations = [item for item in (
                        discovery_correlation, holdout_correlation) if item is not None]
                    if not correlations or abs(discovery_correlation or 0) < self.policy.minimum_absolute_spearman:
                        continue
                    corroborated = (len(complete) >= threshold
                                    and len(holdout) >= self.policy.minimum_holdout_configurations
                                    and holdout_correlation is not None
                                    and abs(holdout_correlation) >= self.policy.minimum_absolute_spearman
                                    and discovery_correlation * holdout_correlation > 0)
                    contradicted = (holdout_correlation is not None
                                    and abs(holdout_correlation) >= self.policy.minimum_absolute_spearman
                                    and discovery_correlation * holdout_correlation < 0)
                    status = "active" if corroborated else "retired" if contradicted else "candidate"
                    artifacts.append({
                        "kind": "parameter_sensitivity", "status": status,
                        "support_count": len(discovery),
                        "contradiction_count": len(holdout) if contradicted else 0,
                        "payload": {"parameter": name, "metric": objective.metric_name,
                                    "discovery_spearman": discovery_correlation,
                                    "holdout_spearman": holdout_correlation,
                                    "direction": "increases" if discovery_correlation > 0 else "decreases",
                                    "scope": "exact context only",
                                    "discovery_configuration_ids": [
                                        item["configuration_id"] for item in discovery],
                                    "holdout_configuration_ids": [
                                        item["configuration_id"] for item in holdout],
                                    "retirement_reason": (
                                        "holdout direction contradicts discovery"
                                        if contradicted else None)},
                    })
            numeric_names = [name for name in names if all(
                isinstance(item["parameters"][name], (int, float))
                and not isinstance(item["parameters"][name], bool)
                for item in complete)]
            for first_index, first in enumerate(numeric_names[:16]):
                for second in numeric_names[first_index + 1:16]:
                    for objective in objectives:
                        discovery_effect = _interaction_effect(
                            discovery, first, second, objective.metric_name)
                        holdout_effect = _interaction_effect(
                            holdout, first, second, objective.metric_name)
                        if (discovery_effect is None or abs(discovery_effect)
                                < self.policy.minimum_standardized_interaction):
                            continue
                        corroborated = (
                            len(complete) >= threshold
                            and len(holdout) >= self.policy.minimum_holdout_configurations
                            and holdout_effect is not None
                            and abs(holdout_effect)
                            >= self.policy.minimum_standardized_interaction
                            and discovery_effect * holdout_effect > 0)
                        contradicted = (
                            holdout_effect is not None
                            and abs(holdout_effect)
                            >= self.policy.minimum_standardized_interaction
                            and discovery_effect * holdout_effect < 0)
                        artifacts.append({
                            "kind": "parameter_interaction",
                            "status": ("active" if corroborated else
                                       "retired" if contradicted else "candidate"),
                            "support_count": len(discovery),
                            "contradiction_count": len(holdout) if contradicted else 0,
                            "payload": {
                                "parameters": [first, second],
                                "metric": objective.metric_name,
                                "discovery_standardized_effect": discovery_effect,
                                "holdout_standardized_effect": holdout_effect,
                                "scope": "exact context only",
                                "discovery_configuration_ids": [
                                    item["configuration_id"] for item in discovery],
                                "holdout_configuration_ids": [
                                    item["configuration_id"] for item in holdout],
                                "retirement_reason": (
                                    "holdout interaction sign contradicts discovery"
                                    if contradicted else None),
                            },
                        })
        return artifacts

    def snapshot(self, context_fingerprint: str) -> dict[str, Any]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM optimization_memory_artifacts_v1 WHERE context_fingerprint=? ORDER BY kind,artifact_id",
                (context_fingerprint,)).fetchall()
            observation_count = connection.execute(
                "SELECT COUNT(*) FROM optimization_memory_observations_v1 WHERE context_fingerprint=?",
                (context_fingerprint,)).fetchone()[0]
            unique_count = connection.execute(
                "SELECT COUNT(DISTINCT effective_configuration_id) FROM optimization_memory_observations_v1 WHERE context_fingerprint=?",
                (context_fingerprint,)).fetchone()[0]
        artifacts = [{"artifact_id": row["artifact_id"], "kind": row["kind"],
                      "status": row["status"], "support_count": row["support_count"],
                      "contradiction_count": row["contradiction_count"],
                      "payload": json.loads(row["payload_json"]),
                      "fingerprint": row["fingerprint"]} for row in rows]
        return {"schema_version": 1, "context_fingerprint": context_fingerprint,
                "observation_count": observation_count,
                "unique_configuration_count": unique_count,
                "artifacts": artifacts,
                "active_artifacts": [item for item in artifacts if item["status"] == "active"],
                "evidence_verification": ("runtime_resolved" if self.evidence_verifier
                                          else "structural_only"),
                "claim_boundary": "only active exact-context artifacts may guide proposals; candidate, retired, and unvalidated transfer artifacts are inert"}

    def propose_transfers(self, source_context_fingerprint: str,
                          target_context_fingerprint: str) -> list[dict[str, Any]]:
        """Create inert cross-design candidates from source holdout-validated rules."""
        if source_context_fingerprint == target_context_fingerprint:
            raise ValueError("Transfer requires distinct source and target contexts")
        source_observations = self.observations(source_context_fingerprint)
        target_observations = self.observations(target_context_fingerprint)
        if not source_observations or not target_observations:
            raise ValueError("Both transfer contexts require observed Runtime evidence")
        source_context = source_observations[0].context
        target_context = target_observations[0].context
        comparable = all(getattr(source_context, name) == getattr(target_context, name)
                         for name in ("platform", "pdk_id", "toolchain_id",
                                      "flow_stage", "metric_parser_version"))
        if not comparable:
            raise ValueError("Transfer contexts differ in platform/toolchain/parser semantics")
        source = self.snapshot(source_context_fingerprint)
        candidates = [item for item in source["active_artifacts"]
                      if item["kind"] in {"parameter_sensitivity", "parameter_interaction"}]
        with self._connect() as connection:
            for artifact in candidates:
                transfer_id = f"transfer-{_digest({'target': target_context_fingerprint, 'source': artifact['fingerprint']})[:24]}"
                payload = {
                    "source_artifact": artifact,
                    "source_design_id": source_context.design_id,
                    "target_design_id": target_context.design_id,
                    "target_holdout_artifact": None,
                    "execution_allowed": False,
                    "claim_boundary": "cross-design candidate; inert until target holdout validation",
                }
                connection.execute(
                    """INSERT OR IGNORE INTO optimization_memory_transfer_v1
                       (transfer_id,source_context_fingerprint,target_context_fingerprint,
                        source_artifact_fingerprint,kind,status,payload_json)
                       VALUES (?,?,?,?,?,'candidate',?)""",
                    (transfer_id, source_context_fingerprint,
                     target_context_fingerprint, artifact["fingerprint"],
                     artifact["kind"], json.dumps(payload)),
                )
        return self.transfers(target_context_fingerprint)

    def validate_transfer(self, transfer_id: str,
                          objectives: Iterable[ObjectiveSpec]) -> dict[str, Any]:
        """Activate transfer only when an independent target artifact agrees."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM optimization_memory_transfer_v1 WHERE transfer_id=?",
                (transfer_id,),
            ).fetchone()
        if row is None:
            raise KeyError(transfer_id)
        target_snapshot = self.rebuild(
            row["target_context_fingerprint"], tuple(objectives))
        payload = json.loads(row["payload_json"])
        source = payload["source_artifact"]
        matching = next((item for item in target_snapshot["active_artifacts"]
                         if item["kind"] == source["kind"]
                         and _artifact_signature(item) == _artifact_signature(source)), None)
        enough_target_evidence = (
            target_snapshot["unique_configuration_count"]
            >= self.policy.minimum_corroborating_configurations)
        status = ("active" if matching else
                  "rejected" if enough_target_evidence else "candidate")
        payload.update({
            "target_holdout_artifact": matching,
            "execution_allowed": False,
            "claim_boundary": (
                "target holdout independently corroborated transfer semantics"
                if status == "active" else
                "target evidence contradicted the source rule; transfer is inert"
                if status == "rejected" else
                "target holdout evidence is insufficient; transfer remains inert"
            ),
        })
        with self._connect() as connection:
            connection.execute(
                """UPDATE optimization_memory_transfer_v1
                   SET status=?, payload_json=?, updated_at=CURRENT_TIMESTAMP
                   WHERE transfer_id=?""",
                (status, json.dumps(payload), transfer_id),
            )
        return next(item for item in self.transfers(
            row["target_context_fingerprint"]) if item["transfer_id"] == transfer_id)

    def transfers(self, target_context_fingerprint: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT * FROM optimization_memory_transfer_v1
                   WHERE target_context_fingerprint=? ORDER BY transfer_id""",
                (target_context_fingerprint,),
            ).fetchall()
        return [{"transfer_id": row["transfer_id"], "kind": row["kind"],
                 "status": row["status"],
                 "source_context_fingerprint": row["source_context_fingerprint"],
                 "target_context_fingerprint": row["target_context_fingerprint"],
                 "source_artifact_fingerprint": row["source_artifact_fingerprint"],
                 "payload": json.loads(row["payload_json"]),
                 "created_at": row["created_at"], "updated_at": row["updated_at"]}
                for row in rows]

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection


def _artifact_signature(artifact: dict[str, Any]) -> tuple[Any, ...]:
    payload = artifact["payload"]
    if artifact["kind"] == "parameter_sensitivity":
        return (artifact["kind"], payload["parameter"], payload["metric"],
                payload["direction"])
    effect = float(payload["discovery_standardized_effect"])
    return (artifact["kind"], tuple(payload["parameters"]), payload["metric"],
            1 if effect > 0 else -1)
