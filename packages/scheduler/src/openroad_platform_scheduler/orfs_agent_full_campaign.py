"""Durable control plane for the complete upstream ORFS-Agent L2 loop.

The platform schedules typed tasks and records evidence.  Candidate generation
remains in the pinned upstream initializer and GP/EI adapter; candidate QoR
remains under Runtime and the protected evaluator.
"""
from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Mapping, Sequence

from openroad_platform_execution import (
    ORFSAgentFullDomain,
    build_orfs_agent_full_candidate_task,
    build_orfs_agent_full_initialization_task,
    build_orfs_agent_full_policy_task,
)


ORFS_AGENT_FULL_CAMPAIGN_KIND = "orfs-agent-full-campaign-v1"
TERMINAL = frozenset({"succeeded", "failed", "cancelled", "timed_out", "lost"})
FINAL = frozenset({"completed", "failed", "diagnosis_required"})


class ORFSAgentFullCampaignService:
    """Execute initialization -> measurement -> GP/EI -> feedback -> confirmation.

    ``observation_for_run`` must return the artifact-backed full-domain row for
    a Runtime candidate run.  ``candidates_for_run`` reads only a registered
    optimizer-candidate artifact.  These callbacks keep file layout and
    evidence parsing out of the scheduler while Runtime remains authoritative.
    """

    def __init__(
        self, *, checkpoints: Any, runtime: Any, runtime_store: Any,
        observation_for_run: Callable[[str, Mapping[str, Any]], Mapping[str, Any]],
        candidates_for_run: Callable[[str], Sequence[Mapping[str, Any]]],
    ) -> None:
        self.checkpoints = checkpoints
        self.runtime = runtime
        self.runtime_store = runtime_store
        self.observation_for_run = observation_for_run
        self.candidates_for_run = candidates_for_run

    def configure(
        self, pipeline_id: str, *, domain: ORFSAgentFullDomain, objective: str,
        initialization_seed: int, screening_seed: int,
        confirmation_seeds: Sequence[int],
    ) -> dict[str, Any]:
        """Freeze execution seeds and the exact domain on an authorized handoff."""
        checkpoint = self._checkpoint(pipeline_id)
        state = dict(checkpoint["state"])
        if state.get("status") != "authorized":
            if state.get("campaign_fingerprint") == self._fingerprint(
                domain, objective, initialization_seed, screening_seed,
                confirmation_seeds,
            ):
                return checkpoint
            raise ValueError("ORFS-Agent campaign is already configured differently")
        request = state.get("request")
        if (not isinstance(request, Mapping) or request.get("plugin_id") != "orfs-agent"
                or request.get("capability") != "optimizer.l2.upstream-full-12d"):
            raise ValueError("authorized controller is not bound to full ORFS-Agent")
        # Policy-only readiness is not L2 readiness.  The same admitted plugin
        # must also be able to execute the candidates it proposes.
        self.runtime.registry.resolve(
            "orfs-agent", capability="optimizer.l2.upstream-full-candidate")
        if objective not in domain.experiment_protocol["objective_set"]:
            raise ValueError("campaign objective is outside the frozen full-domain protocol")
        budget = domain.experiment_protocol["budget"]
        required_eda_runs = (
            int(budget["initial_samples"])
            + int(budget["rounds"]) * int(budget["suggestions_per_round"])
            + int(budget["confirmations"])
        )
        request_budget = request.get("budget")
        if (not isinstance(request_budget, Mapping)
                or int(request_budget.get("max_eda_runs") or 0) < required_eda_runs):
            raise ValueError(
                f"authorized L2 EDA budget is below the frozen full campaign requirement "
                f"({required_eda_runs})"
            )
        for name, seed in (("initialization_seed", initialization_seed),
                           ("screening_seed", screening_seed)):
            if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        confirmations = list(confirmation_seeds)
        required = int(domain.experiment_protocol["budget"]["confirmations"])
        if (len(confirmations) != required or len(set(confirmations)) != len(confirmations)
                or any(isinstance(seed, bool) or not isinstance(seed, int) or seed < 0
                       for seed in confirmations)):
            raise ValueError("confirmation seeds must be distinct and match the frozen budget")
        fingerprint = self._fingerprint(
            domain, objective, initialization_seed, screening_seed, confirmations,
        )
        state.update({
            "status": "initialization_pending",
            "domain": domain.to_dict(), "objective": objective,
            "initialization_seed": initialization_seed,
            "screening_seed": screening_seed,
            "confirmation_seeds": confirmations,
            "campaign_fingerprint": fingerprint,
            "initialization_run_id": None,
            "initial_candidates": [], "observations": [],
            "optimizer_observations": [], "policy_run_id": None,
            "active_candidates": [], "history": [], "round": 0,
            "confirmation_runs": [],
            "required_eda_runs": required_eda_runs,
            "claim_boundary": (
                "full 12-D variable-clock protocol configured; no candidate is "
                "canonical until Runtime and the protected evaluator attest it"
            ),
        })
        return self._save(checkpoint, state)

    def advance(self, pipeline_id: str, *, execute: bool = False,
                max_parallel: int = 1) -> dict[str, Any]:
        checkpoint = self._checkpoint(pipeline_id)
        state = checkpoint["state"]
        request_budget = (state.get("request") or {}).get("budget")
        authorized_parallel = (request_budget.get("max_parallel")
                               if isinstance(request_budget, Mapping) else None)
        if (isinstance(max_parallel, bool) or not isinstance(max_parallel, int)
                or max_parallel < 1):
            raise ValueError("full campaign max_parallel must be a positive integer")
        if (isinstance(authorized_parallel, bool)
                or not isinstance(authorized_parallel, int)
                or authorized_parallel < 1):
            raise ValueError("authorized L2 request lacks a valid parallelism budget")
        if max_parallel > authorized_parallel:
            raise ValueError("full campaign max_parallel exceeds the authorized L2 budget")
        status = str(state.get("status"))
        if status in FINAL or status == "authorized":
            return checkpoint
        domain = ORFSAgentFullDomain.from_dict(state["domain"])

        if status == "initialization_pending":
            task = build_orfs_agent_full_initialization_task(
                project_id=self._project_id(state), design_id=domain.design,
                objective=state["objective"], domain=domain,
                count=int(domain.experiment_protocol["budget"]["initial_samples"]),
                initialization_seed=int(state["initialization_seed"]),
                task_id=f"{pipeline_id}-initialize",
            )
            run = self.runtime.submit_idempotent(
                task, capability="optimizer.l2.upstream-full-12d")
            state = dict(state)
            state.update({"initialization_run_id": run.run_id,
                          "status": "initialization_running"})
            return self._save(checkpoint, state)

        if status == "initialization_running":
            run_id = str(state["initialization_run_id"])
            self._execute((run_id,), execute, 1)
            if not self._all_terminal((run_id,)):
                return self.checkpoints.get(pipeline_id)
            if self.runtime_store.get_run(run_id).status.value != "succeeded":
                return self._fail(checkpoint, "upstream initialization Runtime task failed")
            try:
                candidates = [dict(item) for item in self.candidates_for_run(run_id)]
                expected = int(domain.experiment_protocol["budget"]["initial_samples"])
                if len(candidates) != expected:
                    raise ValueError("initializer candidate count differs from frozen budget")
                for candidate in candidates:
                    domain.validate_candidate(candidate)
            except (OSError, KeyError, TypeError, ValueError) as exc:
                return self._fail(checkpoint, f"upstream initialization artifact is invalid: {exc}")
            state = dict(state)
            state.update({"initial_candidate_values": candidates,
                          "status": "initial_candidates_pending"})
            checkpoint = self._save(checkpoint, state)
            return self._submit_candidates(checkpoint, candidates, role="initial")

        if status == "initial_candidates_pending":
            return self._submit_candidates(
                checkpoint, state["initial_candidate_values"], role="initial")

        if status == "initial_candidates_running":
            run_ids = [item["run_id"] for item in state["initial_candidates"]]
            self._execute(run_ids, execute, max_parallel)
            if not self._all_terminal(run_ids):
                return self.checkpoints.get(pipeline_id)
            observed = self._observe_batch(state["initial_candidates"], state, domain)
            usable = [item for item in observed if self._usable(item, state["objective"])]
            state = dict(state)
            state.update({"observations": observed, "optimizer_observations": usable,
                          "status": "policy_pending"})
            checkpoint = self._save(checkpoint, state)
            if len(usable) < 2:
                return self._diagnosis(
                    checkpoint,
                    "initialization produced fewer than two artifact-backed objective rows",
                )
            return checkpoint

        if status == "policy_pending":
            round_index = int(state["round"])
            task = build_orfs_agent_full_policy_task(
                project_id=self._project_id(state), design_id=domain.design,
                objective=state["objective"],
                observations=state["optimizer_observations"], domain=domain,
                n_suggestions=int(domain.experiment_protocol["budget"]["suggestions_per_round"]),
                optimizer_seed=int(state["initialization_seed"]) + round_index,
                task_id=f"{pipeline_id}-policy-{round_index}",
            )
            run = self.runtime.submit_idempotent(
                task, capability="optimizer.l2.upstream-full-12d")
            state = dict(state)
            state.update({"policy_run_id": run.run_id, "status": "policy_running"})
            return self._save(checkpoint, state)

        if status == "policy_running":
            run_id = str(state["policy_run_id"])
            self._execute((run_id,), execute, 1)
            if not self._all_terminal((run_id,)):
                return self.checkpoints.get(pipeline_id)
            if self.runtime_store.get_run(run_id).status.value != "succeeded":
                return self._fail(checkpoint, "upstream GP/EI Runtime task failed")
            try:
                candidates = [dict(item) for item in self.candidates_for_run(run_id)]
                expected = int(domain.experiment_protocol["budget"]["suggestions_per_round"])
                if len(candidates) != expected:
                    raise ValueError("policy candidate count differs from frozen budget")
                for candidate in candidates:
                    domain.validate_candidate(candidate)
            except (OSError, KeyError, TypeError, ValueError) as exc:
                return self._fail(checkpoint, f"upstream GP/EI candidate artifact is invalid: {exc}")
            state = dict(state)
            state.update({"active_candidate_values": candidates,
                          "active_candidates": [], "status": "candidates_pending"})
            checkpoint = self._save(checkpoint, state)
            return self._submit_candidates(checkpoint, candidates, role="round")

        if status == "candidates_pending":
            return self._submit_candidates(
                checkpoint, state["active_candidate_values"], role="round")

        if status == "candidates_running":
            run_ids = [item["run_id"] for item in state["active_candidates"]]
            self._execute(run_ids, execute, max_parallel)
            if not self._all_terminal(run_ids):
                return self.checkpoints.get(pipeline_id)
            observed = self._observe_batch(state["active_candidates"], state, domain)
            usable = [item for item in observed if self._usable(item, state["objective"])]
            next_round = int(state["round"]) + 1
            history = [*state["history"], {
                "round": int(state["round"]), "policy_run_id": state["policy_run_id"],
                "candidates": state["active_candidates"], "terminal_observations": observed,
                "optimizer_feedback_count": len(usable),
            }]
            state = dict(state)
            state.update({
                "observations": [*state["observations"], *observed],
                "optimizer_observations": [*state["optimizer_observations"], *usable],
                "history": history, "round": next_round, "active_candidates": [],
                "policy_run_id": None,
            })
            if next_round < int(domain.experiment_protocol["budget"]["rounds"]):
                state["status"] = "policy_pending"
                return self._save(checkpoint, state)
            incumbent = self._incumbent(state["optimizer_observations"], state["objective"])
            if incumbent is None:
                return self._diagnosis(
                    self._save(checkpoint, {**state, "status": "confirmation_pending"}),
                    "campaign produced no artifact-backed objective row",
                )
            state.update({"incumbent": incumbent, "status": "confirmation_pending"})
            checkpoint = self._save(checkpoint, state)
            return self._submit_confirmations(checkpoint)

        if status == "confirmation_pending":
            return self._submit_confirmations(checkpoint)

        if status == "confirmation_running":
            run_ids = [item["run_id"] for item in state["confirmation_runs"]]
            self._execute(run_ids, execute, max_parallel)
            if not self._all_terminal(run_ids):
                return self.checkpoints.get(pipeline_id)
            observed = self._observe_batch(state["confirmation_runs"], state, domain)
            usable = [item for item in observed if self._usable(item, state["objective"])]
            state = dict(state)
            state.update({
                "confirmation_observations": observed,
                "status": "completed" if len(usable) == len(run_ids) else "diagnosis_required",
                "completion_reason": (
                    "full_budget_and_independent_confirmations_completed"
                    if len(usable) == len(run_ids)
                    else "one_or_more_confirmation_runs_lacked_canonical_evidence"
                ),
            })
            return self._save(checkpoint, state)

        return self._fail(checkpoint, f"unsupported full ORFS-Agent campaign state: {status}")

    def _submit_candidates(self, checkpoint: Mapping[str, Any],
                           candidates: Sequence[Mapping[str, Any]], *, role: str) -> dict[str, Any]:
        state = dict(checkpoint["state"])
        domain = ORFSAgentFullDomain.from_dict(state["domain"])
        key = "initial_candidates" if role == "initial" else "active_candidates"
        runs = list(state.get(key) or [])
        round_index = int(state["round"])
        for index in range(len(runs), len(candidates)):
            candidate = dict(candidates[index]); domain.validate_candidate(candidate)
            prefix = "initial" if role == "initial" else f"round-{round_index}"
            task = build_orfs_agent_full_candidate_task(
                project_id=self._project_id(state), design_id=domain.design,
                objective=state["objective"], domain=domain, candidate=candidate,
                or_seed=int(state["screening_seed"]),
                task_id=f"{checkpoint['pipeline_id']}-{prefix}-candidate-{index}",
            )
            run = self.runtime.submit_idempotent(
                task, capability="optimizer.l2.upstream-full-candidate")
            runs.append({"candidate": candidate, "run_id": run.run_id,
                         "or_seed": int(state["screening_seed"])})
            state[key] = runs
            checkpoint = self._save(checkpoint, state)
        state = dict(checkpoint["state"])
        state["status"] = ("initial_candidates_running" if role == "initial"
                           else "candidates_running")
        return self._save(checkpoint, state)

    def _submit_confirmations(self, checkpoint: Mapping[str, Any]) -> dict[str, Any]:
        state = dict(checkpoint["state"])
        domain = ORFSAgentFullDomain.from_dict(state["domain"])
        candidate = dict(state["incumbent"]["candidate"])
        runs = list(state.get("confirmation_runs") or [])
        for index in range(len(runs), len(state["confirmation_seeds"])):
            seed = int(state["confirmation_seeds"][index])
            task = build_orfs_agent_full_candidate_task(
                project_id=self._project_id(state), design_id=domain.design,
                objective=state["objective"], domain=domain, candidate=candidate,
                or_seed=seed,
                task_id=f"{checkpoint['pipeline_id']}-confirmation-{index}",
            )
            run = self.runtime.submit_idempotent(
                task, capability="optimizer.l2.upstream-full-candidate")
            runs.append({"candidate": candidate, "run_id": run.run_id, "or_seed": seed})
            state["confirmation_runs"] = runs
            checkpoint = self._save(checkpoint, state)
        state = dict(checkpoint["state"]); state["status"] = "confirmation_running"
        return self._save(checkpoint, state)

    def _observe_batch(self, runs: Sequence[Mapping[str, Any]], state: Mapping[str, Any],
                       domain: ORFSAgentFullDomain) -> list[dict[str, Any]]:
        rows = []
        for item in runs:
            run_id = str(item["run_id"])
            try:
                row = dict(self.observation_for_run(run_id, state))
                row.setdefault("run_id", run_id)
                row.setdefault("candidate", dict(item["candidate"]))
                row.setdefault("protocol_sha256", domain.protocol_sha256)
                row.setdefault("artifact_refs", [])
                domain.validate_observation(row)
            except (OSError, KeyError, TypeError, ValueError) as exc:
                row = {
                    "run_id": run_id, "observation_id": f"unreadable-{run_id}",
                    "status": self.runtime_store.get_run(run_id).status.value,
                    "candidate": dict(item["candidate"]),
                    "protocol_sha256": domain.protocol_sha256,
                    "metrics": {}, "artifact_refs": [], "feasible": False,
                    "failure_category": f"evidence_error:{type(exc).__name__}",
                    "failure_message": str(exc),
                }
            rows.append(row)
        return rows

    @staticmethod
    def _usable(row: Mapping[str, Any], objective: str) -> bool:
        if row.get("status") != "succeeded" or not row.get("artifact_refs"):
            return False
        metrics = row.get("metrics")
        if not isinstance(metrics, Mapping):
            return False
        if objective == "ECP":
            return isinstance(metrics.get("ECP_final"), (int, float))
        if objective == "DWL":
            return isinstance(metrics.get("detailedroute__route__wirelength"), (int, float))
        return isinstance(metrics.get("Fractional_Loss_final"), (int, float))

    @staticmethod
    def _incumbent(rows: Sequence[Mapping[str, Any]], objective: str) -> dict[str, Any] | None:
        key = {"ECP": "ECP_final", "DWL": "detailedroute__route__wirelength",
               "COMBO": "Fractional_Loss_final"}[objective]
        eligible = [row for row in rows if isinstance((row.get("metrics") or {}).get(key), (int, float))]
        return dict(min(eligible, key=lambda row: float(row["metrics"][key]))) if eligible else None

    def _execute(self, run_ids: Sequence[str], execute: bool, max_parallel: int) -> None:
        if not execute:
            return
        ready = [run_id for run_id in run_ids
                 if self.runtime_store.get_run(run_id).status.value in {"queued", "retry_wait"}]
        if not ready:
            return
        with ThreadPoolExecutor(max_workers=max(1, min(int(max_parallel), len(ready)))) as pool:
            futures = [pool.submit(self.runtime.execute_once, run_id) for run_id in ready]
            for future in as_completed(futures):
                future.result()

    def _all_terminal(self, run_ids: Sequence[str]) -> bool:
        return bool(run_ids) and all(
            self.runtime_store.get_run(run_id).status.value in TERMINAL for run_id in run_ids)

    def _checkpoint(self, pipeline_id: str) -> dict[str, Any]:
        checkpoint = self.checkpoints.get(pipeline_id)
        if checkpoint["pipeline_kind"] != ORFS_AGENT_FULL_CAMPAIGN_KIND:
            raise KeyError(pipeline_id)
        return checkpoint

    @staticmethod
    def _project_id(state: Mapping[str, Any]) -> str:
        goal = state.get("goal")
        if not isinstance(goal, Mapping) or not isinstance(goal.get("project_id"), str):
            raise ValueError("full campaign checkpoint lacks its authorized Goal")
        return str(goal["project_id"])

    @staticmethod
    def _fingerprint(domain: ORFSAgentFullDomain, objective: str,
                     initialization_seed: int, screening_seed: int,
                     confirmation_seeds: Sequence[int]) -> str:
        value = {"domain": domain.to_dict(), "objective": objective,
                 "initialization_seed": initialization_seed,
                 "screening_seed": screening_seed,
                 "confirmation_seeds": list(confirmation_seeds)}
        return hashlib.sha256(json.dumps(
            value, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()

    def _save(self, checkpoint: Mapping[str, Any], state: Mapping[str, Any]) -> dict[str, Any]:
        return self.checkpoints.save(
            checkpoint["pipeline_id"], state,
            expected_revision=int(checkpoint["revision"]),
        )

    def _fail(self, checkpoint: Mapping[str, Any], reason: str) -> dict[str, Any]:
        state = dict(checkpoint["state"])
        state.update({"status": "failed", "failure": reason})
        return self._save(checkpoint, state)

    def _diagnosis(self, checkpoint: Mapping[str, Any], reason: str) -> dict[str, Any]:
        state = dict(checkpoint["state"])
        state.update({"status": "diagnosis_required", "diagnosis": {
            "reason": reason,
            "boundary": "L3/L4 actions are outside this L2 campaign",
        }})
        return self._save(checkpoint, state)
