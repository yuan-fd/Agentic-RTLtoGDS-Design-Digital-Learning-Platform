"""Durable quick-to-full evaluation scheduler for expensive ORFS campaigns."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from openroad_platform_contracts import RuntimeStatus, TaskSpec, TERMINAL_RUNTIME_STATUSES

from .runtime import WorkflowRuntime
from .execution_backends import LocalThreadExecutionBackend, ParallelExecutionBackend


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class FidelityPolicy:
    quick_stage: str = "cts"
    full_stage: str = "finish"
    promotion_fraction: float = .30
    minimum_full_evaluations: int = 4
    minimum_calibration_pairs: int = 12
    minimum_rank_correlation: float = .60
    max_parallel: int = 4
    quick_repetitions: int = 1
    full_repetitions: int = 1
    skip_quick: bool = False

    def validate(self) -> None:
        stages = ("synth", "floorplan", "place", "cts", "route", "finish")
        if self.quick_stage not in stages or self.full_stage not in stages:
            raise ValueError("Unknown fidelity stage")
        if stages.index(self.quick_stage) >= stages.index(self.full_stage):
            raise ValueError("quick_stage must precede full_stage")
        if not 0 < self.promotion_fraction <= 1:
            raise ValueError("promotion_fraction must be in (0,1]")
        if not 1 <= self.minimum_full_evaluations <= 128:
            raise ValueError("minimum_full_evaluations must be between 1 and 128")
        if not 3 <= self.minimum_calibration_pairs <= 10_000:
            raise ValueError("minimum_calibration_pairs must be between 3 and 10000")
        if not -1 <= self.minimum_rank_correlation <= 1:
            raise ValueError("minimum_rank_correlation must be between -1 and 1")
        if not 1 <= self.max_parallel <= 64:
            raise ValueError("max_parallel must be between 1 and 64")
        if not 1 <= self.quick_repetitions <= 8:
            raise ValueError("quick_repetitions must be between 1 and 8")
        if not 1 <= self.full_repetitions <= 8:
            raise ValueError("full_repetitions must be between 1 and 8")
        if not isinstance(self.skip_quick, bool):
            raise ValueError("skip_quick must be boolean")

    def to_dict(self) -> dict[str, Any]:
        self.validate(); return dataclasses.asdict(self)


def proxy_calibration(pairs: Sequence[tuple[float, float]], *, minimum_pairs: int = 12,
                      minimum_correlation: float = .60) -> dict[str, Any]:
    if len(pairs) < minimum_pairs:
        return {"eligible": False, "pair_count": len(pairs), "spearman": None,
                "reason": "insufficient paired quick/full evaluations"}
    from scipy.stats import spearmanr
    quick, full = zip(*pairs)
    correlation = float(spearmanr(quick, full).statistic)
    eligible = math.isfinite(correlation) and correlation >= minimum_correlation
    return {"eligible": eligible, "pair_count": len(pairs), "spearman": correlation,
            "threshold": minimum_correlation,
            "reason": "calibrated" if eligible else "quick fidelity is not predictive enough"}


def promotion_decision(candidates: Sequence[Mapping[str, Any]], policy: FidelityPolicy,
                       calibration: Mapping[str, Any]) -> dict[str, Any]:
    """Select a bounded full-flow subset without treating quick QoR as final."""
    policy.validate()
    valid = [dict(item) for item in candidates if item.get("quick_succeeded")]
    if not valid:
        return {"promoted_ids": [], "reason": "no successful quick evaluations",
                "quick_metrics_are_final": False}
    # Before the proxy is calibrated, full-evaluate all candidates. This costs
    # more, but prevents an unvalidated intermediate metric from silently
    # deleting the true optimum.
    if not calibration.get("eligible"):
        promoted = [item["candidate_id"] for item in valid]
        return {"promoted_ids": promoted, "reason": calibration.get("reason"),
                "mode": "calibration_full_replay", "quick_metrics_are_final": False}
    if any(item.get("quick_proxy_score") is None for item in valid):
        promoted = [item["candidate_id"] for item in valid]
        return {
            "promoted_ids": promoted,
            "reason": "current quick evaluation lacks the calibrated proxy score",
            "mode": "proxy_missing_full_replay", "quick_metrics_are_final": False,
        }
    count = max(policy.minimum_full_evaluations,
                math.ceil(len(valid) * policy.promotion_fraction))
    count = min(count, len(valid))
    ranked = sorted(valid, key=lambda item: (
        -float(item["quick_proxy_score"]),
        -float(item.get("proposal_acquisition") or 0),
        float(item.get("quick_runtime_seconds") or math.inf),
        item["candidate_id"],
    ))
    promoted = [item["candidate_id"] for item in ranked[:count]]
    return {"promoted_ids": promoted, "reason": "calibrated acquisition-per-runtime ranking",
            "mode": "risk_aware_promotion", "quick_metrics_are_final": False,
            "candidate_count": len(valid), "promotion_count": len(promoted)}


class MultiFidelityStore:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve(); self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS multifidelity_campaigns_v1 (
                    campaign_id TEXT PRIMARY KEY, policy_json TEXT NOT NULL,
                    state TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS multifidelity_candidates_v1 (
                    campaign_id TEXT NOT NULL, candidate_id TEXT NOT NULL,
                    effective_configuration_id TEXT NOT NULL, task_json TEXT NOT NULL,
                    proposal_acquisition REAL NOT NULL, quick_run_id TEXT, full_run_id TEXT,
                    decision_json TEXT, PRIMARY KEY(campaign_id, candidate_id),
                    UNIQUE(campaign_id, effective_configuration_id),
                    UNIQUE(quick_run_id), UNIQUE(full_run_id),
                    FOREIGN KEY(campaign_id) REFERENCES multifidelity_campaigns_v1(campaign_id)
                );
                CREATE TABLE IF NOT EXISTS multifidelity_evaluations_v2 (
                    campaign_id TEXT NOT NULL, candidate_id TEXT NOT NULL,
                    fidelity TEXT NOT NULL, replica_index INTEGER NOT NULL,
                    or_seed INTEGER NOT NULL, run_id TEXT NOT NULL UNIQUE,
                    PRIMARY KEY(campaign_id, candidate_id, fidelity, replica_index),
                    FOREIGN KEY(campaign_id, candidate_id)
                        REFERENCES multifidelity_candidates_v1(campaign_id, candidate_id),
                    CHECK(fidelity IN ('quick', 'full')),
                    CHECK(replica_index >= 0)
                );
            """)
            columns = {row[1] for row in connection.execute(
                "PRAGMA table_info(multifidelity_candidates_v1)")}
            if "replica_seeds_json" not in columns:
                connection.execute(
                    "ALTER TABLE multifidelity_candidates_v1 ADD COLUMN replica_seeds_json TEXT")

    def create(self, policy: FidelityPolicy, candidates: Iterable[Mapping[str, Any]], *,
               campaign_id: str | None = None) -> str:
        policy.validate(); rows = tuple(dict(item) for item in candidates)
        if not rows:
            raise ValueError("A multi-fidelity campaign requires candidates")
        identifier = campaign_id or f"multifidelity-{uuid.uuid4().hex}"
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("INSERT INTO multifidelity_campaigns_v1 VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                               (identifier, json.dumps(policy.to_dict()), "quick_pending"))
            for item in rows:
                task = item.get("task")
                if isinstance(task, TaskSpec): task = task.to_dict()
                validated = TaskSpec.from_dict(task)
                candidate_id = str(item.get("candidate_id") or "")
                if not candidate_id:
                    raise ValueError("candidate_id is required")
                effective_id = str(item.get("effective_configuration_id") or
                                   _digest(validated.parameters.get("flow_parameters", {})))
                seeds = tuple(int(seed) for seed in (
                    item.get("replica_or_seeds") or
                    (validated.parameters.get("or_seed", 1),)
                ))
                required = max(policy.quick_repetitions, policy.full_repetitions)
                if len(seeds) < required or len(set(seeds)) != len(seeds) or any(
                    seed < 0 or seed > 2_147_483_647 for seed in seeds
                ):
                    raise ValueError(
                        "replica_or_seeds must provide distinct valid seeds for the fidelity policy"
                    )
                try:
                    connection.execute(
                        """INSERT INTO multifidelity_candidates_v1
                           (campaign_id, candidate_id, effective_configuration_id,
                            task_json, proposal_acquisition, quick_run_id,
                            full_run_id, decision_json, replica_seeds_json)
                           VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, ?)""",
                        (identifier, candidate_id, effective_id,
                         json.dumps(validated.to_dict()),
                         float(item.get("proposal_acquisition") or 0),
                         json.dumps(seeds)),
                    )
                except sqlite3.IntegrityError as exc:
                    raise ValueError("Duplicate effective configuration in campaign") from exc
        return identifier

    def campaign(self, campaign_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM multifidelity_campaigns_v1 WHERE campaign_id=?",
                                     (campaign_id,)).fetchone()
        if row is None: raise KeyError(campaign_id)
        return {"campaign_id": row["campaign_id"], "policy": json.loads(row["policy_json"]),
                "state": row["state"], "created_at": row["created_at"]}

    def candidates(self, campaign_id: str) -> list[dict[str, Any]]:
        self.campaign(campaign_id)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM multifidelity_candidates_v1 WHERE campaign_id=? ORDER BY candidate_id",
                (campaign_id,)).fetchall()
        result = []
        for row in rows:
            evaluations = self.evaluations(campaign_id, row["candidate_id"])
            quick_ids = tuple(item["run_id"] for item in evaluations
                              if item["fidelity"] == "quick")
            full_ids = tuple(item["run_id"] for item in evaluations
                             if item["fidelity"] == "full")
            legacy_seed = json.loads(row["task_json"])["parameters"].get("or_seed", 1)
            seeds = json.loads(row["replica_seeds_json"] or json.dumps([legacy_seed]))
            result.append({
                "campaign_id": row["campaign_id"], "candidate_id": row["candidate_id"],
                "effective_configuration_id": row["effective_configuration_id"],
                "task": json.loads(row["task_json"]),
                "proposal_acquisition": row["proposal_acquisition"],
                "replica_or_seeds": seeds,
                "quick_run_id": quick_ids[0] if quick_ids else row["quick_run_id"],
                "full_run_id": full_ids[0] if full_ids else row["full_run_id"],
                "quick_run_ids": quick_ids, "full_run_ids": full_ids,
                "decision": json.loads(row["decision_json"]) if row["decision_json"] else None,
            })
        return result

    def evaluations(self, campaign_id: str, candidate_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT * FROM multifidelity_evaluations_v2
                   WHERE campaign_id=? AND candidate_id=?
                   ORDER BY fidelity, replica_index""",
                (campaign_id, candidate_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def bind_run(self, campaign_id: str, candidate_id: str, *, fidelity: str,
                 replica_index: int = 0, or_seed: int = 1, run_id: str) -> None:
        column = {"quick": "quick_run_id", "full": "full_run_id"}.get(fidelity)
        if not column: raise ValueError("fidelity must be quick or full")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            exists = connection.execute(
                "SELECT 1 FROM multifidelity_candidates_v1 WHERE campaign_id=? AND candidate_id=?",
                (campaign_id, candidate_id),
            ).fetchone()
            if not exists:
                raise ValueError("Candidate is missing")
            try:
                connection.execute(
                    """INSERT INTO multifidelity_evaluations_v2
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (campaign_id, candidate_id, fidelity, replica_index, or_seed, run_id),
                )
            except sqlite3.IntegrityError as exc:
                existing = connection.execute(
                    """SELECT run_id FROM multifidelity_evaluations_v2
                       WHERE campaign_id=? AND candidate_id=? AND fidelity=? AND replica_index=?""",
                    (campaign_id, candidate_id, fidelity, replica_index),
                ).fetchone()
                if existing is None or existing["run_id"] != run_id:
                    raise ValueError("Candidate replica run is already bound") from exc
            if replica_index == 0:
                connection.execute(
                    f"""UPDATE multifidelity_candidates_v1 SET {column}=?
                        WHERE campaign_id=? AND candidate_id=? AND {column} IS NULL""",
                    (run_id, campaign_id, candidate_id),
                )

    def record_decision(self, campaign_id: str, decision: Mapping[str, Any]) -> None:
        promoted = set(decision.get("promoted_ids", ()))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for row in self.candidates(campaign_id):
                payload = {**dict(decision), "promoted": row["candidate_id"] in promoted}
                connection.execute(
                    "UPDATE multifidelity_candidates_v1 SET decision_json=? WHERE campaign_id=? AND candidate_id=?",
                    (json.dumps(payload), campaign_id, row["candidate_id"]))
            connection.execute("UPDATE multifidelity_campaigns_v1 SET state='promotion_recorded' WHERE campaign_id=?",
                               (campaign_id,))

    def set_state(self, campaign_id: str, state: str) -> None:
        with self._connect() as connection:
            if connection.execute("UPDATE multifidelity_campaigns_v1 SET state=? WHERE campaign_id=?",
                                  (state, campaign_id)).rowcount != 1:
                raise KeyError(campaign_id)

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection


class MultiFidelityScheduler:
    def __init__(self, store: MultiFidelityStore, runtime: WorkflowRuntime,
                 execution_backend: ParallelExecutionBackend | None = None):
        self.store, self.runtime = store, runtime
        self.execution_backend = execution_backend or LocalThreadExecutionBackend()

    def ensure_quick_runs(self, campaign_id: str) -> tuple[str, ...]:
        policy = FidelityPolicy(**self.store.campaign(campaign_id)["policy"])
        if policy.skip_quick:
            self.store.set_state(campaign_id, "quick_disabled")
            return ()
        run_ids = []
        for row in self.store.candidates(campaign_id):
            existing = {item["replica_index"]: item for item in self.store.evaluations(
                campaign_id, row["candidate_id"]) if item["fidelity"] == "quick"}
            for replica in range(policy.quick_repetitions):
                bound = existing.get(replica)
                run_id = bound["run_id"] if bound else None
                seed = int(row["replica_or_seeds"][replica])
                if run_id is None:
                    task = TaskSpec.from_dict(row["task"])
                    task = dataclasses.replace(
                        task, task_id=f"{campaign_id}-{row['candidate_id']}-quick-r{replica}",
                        parameters={**task.parameters, "target_stage": policy.quick_stage,
                                    "or_seed": seed},
                        # The template is normally a finish task and therefore
                        # requires DEF/netlist/GDS.  A CTS proxy cannot produce
                        # those by definition.  Leaving the finish contract on
                        # the quick copy made successful CTS runs become Runtime
                        # protocol failures and silently disabled promotion.
                        expected_artifacts=tuple(
                            kind for kind in task.expected_artifacts
                            if kind not in {"def", "netlist", "gds"}
                        ),
                        labels={**task.labels, "fidelity": "quick",
                                "multifidelity_campaign_id": campaign_id,
                                "optimizer_candidate_id": row["candidate_id"],
                                "replica_index": str(replica), "or_seed": str(seed)},
                    )
                    existing_run = self.runtime.store.find_run_by_task_id(task.task_id)
                    run = existing_run or self.runtime.submit(task)
                    self.store.bind_run(
                        campaign_id, row["candidate_id"], fidelity="quick",
                        replica_index=replica, or_seed=seed, run_id=run.run_id,
                    )
                    run_id = run.run_id
                run_ids.append(run_id)
        self.store.set_state(campaign_id, "quick_running")
        return tuple(run_ids)

    def promote(self, campaign_id: str, *,
                calibration_pairs: Sequence[tuple[float, float]] = (),
                quick_scores: Mapping[str, float | None] | None = None) -> dict[str, Any]:
        policy = FidelityPolicy(**self.store.campaign(campaign_id)["policy"])
        rows = []
        for item in self.store.candidates(campaign_id):
            quick_ids = item["quick_run_ids"]
            if policy.skip_quick:
                runs = []
            elif len(quick_ids) != policy.quick_repetitions:
                raise ValueError("Quick replica set is incomplete")
            else:
                runs = [self.runtime.store.get_run(run_id) for run_id in quick_ids]
            if any(run.status not in TERMINAL_RUNTIME_STATUSES for run in runs):
                raise ValueError("Quick evaluations are not terminal")
            rows.append({
                **item,
                "quick_succeeded": (True if policy.skip_quick else
                                    all(run.status is RuntimeStatus.SUCCEEDED for run in runs)),
                "quick_runtime_seconds": sum(
                    _runtime_seconds(self.runtime, run.run_id) for run in runs),
                "quick_proxy_score": (quick_scores or {}).get(item["candidate_id"]),
            })
        calibration = ({"eligible": False, "pair_count": 0, "spearman": None,
                        "reason": "quick fidelity disabled by preregistered ablation"}
                       if policy.skip_quick else proxy_calibration(
                           calibration_pairs,
                           minimum_pairs=policy.minimum_calibration_pairs,
                           minimum_correlation=policy.minimum_rank_correlation))
        decision = promotion_decision(rows, policy, calibration)
        decision["calibration"] = calibration
        self.store.record_decision(campaign_id, decision)
        return decision

    def ensure_full_runs(self, campaign_id: str) -> tuple[str, ...]:
        policy = FidelityPolicy(**self.store.campaign(campaign_id)["policy"])
        run_ids = []
        for row in self.store.candidates(campaign_id):
            if not row["decision"]: raise ValueError("Promotion decision is missing")
            if not row["decision"]["promoted"]: continue
            existing = {item["replica_index"]: item for item in self.store.evaluations(
                campaign_id, row["candidate_id"]) if item["fidelity"] == "full"}
            for replica in range(policy.full_repetitions):
                bound = existing.get(replica)
                run_id = bound["run_id"] if bound else None
                seed = int(row["replica_or_seeds"][replica])
                if run_id is None:
                    task = TaskSpec.from_dict(row["task"])
                    task = dataclasses.replace(
                        task, task_id=f"{campaign_id}-{row['candidate_id']}-full-r{replica}",
                        parameters={**task.parameters, "target_stage": policy.full_stage,
                                    "or_seed": seed},
                        expected_artifacts=tuple(dict.fromkeys((
                            *task.expected_artifacts, "def", "netlist", "gds",
                        ))) if policy.full_stage == "finish" else task.expected_artifacts,
                        labels={**task.labels, "fidelity": "full",
                                "multifidelity_campaign_id": campaign_id,
                                "optimizer_candidate_id": row["candidate_id"],
                                "replica_index": str(replica), "or_seed": str(seed)},
                    )
                    existing_run = self.runtime.store.find_run_by_task_id(task.task_id)
                    run = existing_run or self.runtime.submit(task)
                    self.store.bind_run(
                        campaign_id, row["candidate_id"], fidelity="full",
                        replica_index=replica, or_seed=seed, run_id=run.run_id,
                    )
                    run_id = run.run_id
                run_ids.append(run_id)
        self.store.set_state(campaign_id, "full_running")
        return tuple(run_ids)

    def run_bound(self, run_ids: Sequence[str], *, max_parallel: int) -> dict[str, Any]:
        return self.execution_backend.run_bound(
            self.runtime, run_ids, max_parallel=max_parallel)

    def run_to_terminal(self, campaign_id: str, *, timeout_seconds: float,
                        calibration_pairs: Sequence[tuple[float, float]] = (),
                        quick_scores: Mapping[str, float | None] | None = None) -> dict[str, Any]:
        started = time.monotonic()
        policy = FidelityPolicy(**self.store.campaign(campaign_id)["policy"])
        quick = self.ensure_quick_runs(campaign_id)
        self.run_bound(quick, max_parallel=policy.max_parallel)
        if time.monotonic() - started > timeout_seconds: raise TimeoutError("Quick fidelity timed out")
        decision = self.promote(
            campaign_id, calibration_pairs=calibration_pairs,
            quick_scores=quick_scores,
        )
        full = self.ensure_full_runs(campaign_id)
        self.run_bound(full, max_parallel=policy.max_parallel)
        if time.monotonic() - started > timeout_seconds: raise TimeoutError("Full fidelity timed out")
        self.store.set_state(campaign_id, "completed")
        return {**self.store.campaign(campaign_id), "candidates": self.store.candidates(campaign_id),
                "promotion": decision, "quick_run_ids": quick, "full_run_ids": full}


def _runtime_seconds(runtime: WorkflowRuntime, run_id: str) -> float:
    total = 0.0
    for stage in runtime.describe(run_id)["stages"]:
        for attempt in stage["attempts"]:
            for event in attempt.get("events", ()):  # kept for forward-compatible views
                total += float(event.get("seconds") or 0)
    return total
