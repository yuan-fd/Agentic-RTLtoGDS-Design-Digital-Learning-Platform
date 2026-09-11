"""Durable A2-ORFO policy -> ORFS -> evaluator -> feedback controller.

The external A2-ORFO plugin owns proposal generation. ORFS-Agent remains the
complete 12-D candidate executor, and Runtime/protected evaluator remain the
only measurement authority.
"""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Mapping, Sequence

from openroad_platform_execution import (
    A2_ORFO_UPSTREAM_COMMIT, A2ORFODomain, ORFSAgentFullDomain,
    build_a2_orfo_initialization_task, build_a2_orfo_policy_task,
    build_orfs_agent_full_candidate_task,
)


A2_ORFO_CAMPAIGN_KIND = "a2-orfo-campaign-v1"
TERMINAL = frozenset({"succeeded", "failed", "cancelled", "timed_out", "lost"})
FINAL = frozenset({"completed", "failed", "diagnosis_required"})


class A2ORFOCampaignService:
    """Checkpoint every transition in a bounded native A2 feedback campaign."""

    def __init__(
        self, *, checkpoints: Any, runtime: Any, runtime_store: Any,
        observation_for_run: Callable[[str, Mapping[str, Any]], Mapping[str, Any]],
        policy_result_for_run: Callable[[str], Mapping[str, Any]],
    ) -> None:
        self.checkpoints = checkpoints
        self.runtime = runtime
        self.runtime_store = runtime_store
        self.observation_for_run = observation_for_run
        self.policy_result_for_run = policy_result_for_run

    def configure(
        self, pipeline_id: str, *, a2_domain: A2ORFODomain,
        execution_domain: ORFSAgentFullDomain, objective: str,
        initial_observations: Sequence[Mapping[str, Any]],
        optimizer_seeds: Sequence[int], or_seed: int,
        n_suggestions: int, confirmation_seeds: Sequence[int] = (),
        bootstrap_samples: int | None = None,
    ) -> dict[str, Any]:
        checkpoint = self._checkpoint(pipeline_id)
        state = dict(checkpoint["state"])
        fingerprint = self._fingerprint(
            a2_domain, execution_domain, objective, initial_observations,
            optimizer_seeds, or_seed, n_suggestions, confirmation_seeds,
            bootstrap_samples)
        if state.get("status") != "authorized":
            if state.get("campaign_fingerprint") == fingerprint:
                return checkpoint
            raise ValueError("A2-ORFO campaign is already configured differently")
        request = state.get("request")
        if (not isinstance(request, Mapping) or request.get("plugin_id") != "a2-orfo"
                or request.get("capability") != "optimizer.l2.a2-orfo-feedback"):
            raise ValueError("authorized controller is not bound to A2-ORFO")
        self.runtime.registry.resolve(
            "a2-orfo", capability="optimizer.l2.a2-orfo-initialize")
        self.runtime.registry.resolve(
            "a2-orfo", capability="optimizer.l2.a2-orfo-policy")
        self.runtime.registry.resolve(
            "a2-orfo", capability="optimizer.l2.a2-orfo-feedback")
        self.runtime.registry.resolve(
            "orfs-agent", capability="optimizer.l2.upstream-full-candidate")
        if (a2_domain.design, a2_domain.platform) != (
                execution_domain.design, execution_domain.platform):
            raise ValueError("A2 policy and ORFS execution domains disagree")
        if set(a2_domain.to_dict()["parameter_names"]) != set(
                execution_domain.to_dict()["parameter_names"]):
            raise ValueError("A2 policy and ORFS execution must preserve the same 12 dimensions")
        if objective not in a2_domain.experiment_protocol["objective_set"]:
            raise ValueError("objective is outside the A2-ORFO protocol")
        observations = [dict(item) for item in initial_observations]
        for item in observations:
            a2_domain.validate_observation(item)
        feedback_steps = int(a2_domain.experiment_protocol["budget"]["feedback_steps"])
        required_success = int(
            a2_domain.experiment_protocol["budget"]["minimum_successful_observations"])
        successful = sum(item.get("status") == "succeeded" and bool(item.get("metrics"))
                         for item in observations)
        bootstrap_target = (required_success if bootstrap_samples is None
                            else bootstrap_samples)
        if (isinstance(bootstrap_target, bool)
                or not isinstance(bootstrap_target, int)
                or not required_success <= bootstrap_target <= 64):
            raise ValueError("bootstrap samples must cover the native GPR minimum")
        bootstrap_count = max(0, bootstrap_target - successful)
        seeds = list(optimizer_seeds)
        if (len(seeds) != feedback_steps + 1 or len(set(seeds)) != len(seeds)
                or any(isinstance(seed, bool) or not isinstance(seed, int) or seed < 0
                       for seed in seeds)):
            raise ValueError("optimizer seeds must cover every step plus final feedback")
        confirmations = list(confirmation_seeds)
        if (len(set(confirmations)) != len(confirmations)
                or any(isinstance(seed, bool) or not isinstance(seed, int) or seed < 0
                       for seed in confirmations)):
            raise ValueError("confirmation seeds must be distinct non-negative integers")
        if (isinstance(or_seed, bool) or not isinstance(or_seed, int) or or_seed < 0
                or isinstance(n_suggestions, bool) or not isinstance(n_suggestions, int)
                or not 1 <= n_suggestions <= 64):
            raise ValueError("A2-ORFO candidate count or OR seed is invalid")
        required_eda_runs = (bootstrap_count + feedback_steps * n_suggestions
                             + len(confirmations))
        request_budget = request.get("budget")
        if (not isinstance(request_budget, Mapping)
                or int(request_budget.get("max_eda_runs") or 0) < required_eda_runs):
            raise ValueError(
                f"authorized EDA budget is below A2 campaign requirement ({required_eda_runs})")
        state.update({
            "status": ("bootstrap_pending" if bootstrap_count else "policy_pending"),
            "a2_domain": a2_domain.to_dict(),
            "execution_domain": execution_domain.to_dict(), "objective": objective,
            "initial_observations": observations, "observations": observations,
            "bootstrap_samples": bootstrap_target,
            "bootstrap_count": bootstrap_count, "bootstrap_run_id": None,
            "bootstrap_candidate_values": [], "bootstrap_candidates": [],
            "bootstrap_observations": [],
            "measured_observations": [], "optimizer_seeds": seeds,
            "or_seed": or_seed, "n_suggestions": n_suggestions,
            "confirmation_seeds": confirmations, "feedback_step": 0,
            "policy_run_id": None, "policy_checkpoint": None,
            "policy_evidence_ref": None, "active_candidate_values": [],
            "active_candidates": [], "iterations": [], "final_next_candidates": [],
            "confirmation_runs": [], "confirmation_observations": [],
            "required_eda_runs": required_eda_runs,
            "campaign_fingerprint": fingerprint,
            "optimizer_plugin": f"a2-orfo@{A2_ORFO_UPSTREAM_COMMIT}",
            "executor_plugin": "orfs-agent@730f1fa11f9c17c0aaac332412af2b2538f42e9b",
            "claim_boundary": (
                "A2-ORFO owns policy; ORFS-Agent executes all 12 dimensions; "
                "only protected evaluator artifacts become measured feedback"),
        })
        return self._save(checkpoint, state)

    def advance(self, pipeline_id: str, *, execute: bool = False,
                max_parallel: int = 1) -> dict[str, Any]:
        checkpoint = self._checkpoint(pipeline_id)
        state = checkpoint["state"]
        if str(state.get("status")) in FINAL or state.get("status") == "authorized":
            return checkpoint
        authorized_parallel = ((state.get("request") or {}).get("budget") or {}).get(
            "max_parallel")
        if (isinstance(max_parallel, bool) or not isinstance(max_parallel, int)
                or max_parallel < 1 or isinstance(authorized_parallel, bool)
                or not isinstance(authorized_parallel, int) or authorized_parallel < 1):
            raise ValueError("A2 campaign requires valid positive parallelism")
        if max_parallel > authorized_parallel:
            raise ValueError("A2 campaign parallelism exceeds authorization")
        status = str(state["status"])
        a2_domain = A2ORFODomain.from_dict(state["a2_domain"])
        execution_domain = ORFSAgentFullDomain.from_dict(state["execution_domain"])
        feedback_steps = int(a2_domain.experiment_protocol["budget"]["feedback_steps"])

        if status == "bootstrap_pending":
            task = build_a2_orfo_initialization_task(
                project_id=self._project_id(state), design_id=a2_domain.design,
                objective=state["objective"], domain=a2_domain,
                count=int(state["bootstrap_count"]),
                optimizer_seed=int(state["optimizer_seeds"][0]),
                task_id=f"{pipeline_id}-a2-initialize")
            run = self.runtime.submit_idempotent(
                task, capability="optimizer.l2.a2-orfo-initialize")
            return self._save(checkpoint, {
                **state, "bootstrap_run_id": run.run_id,
                "status": "bootstrap_running"})

        if status == "bootstrap_running":
            run_id = str(state["bootstrap_run_id"])
            self._execute((run_id,), execute, 1)
            if not self._all_terminal((run_id,)):
                return self.checkpoints.get(pipeline_id)
            if self.runtime_store.get_run(run_id).status.value != "succeeded":
                return self._fail(checkpoint, "A2-ORFO native initializer Runtime task failed")
            try:
                result = dict(self.policy_result_for_run(run_id))
                candidates = [dict(item) for item in result["candidates"]]
                if len(candidates) != int(state["bootstrap_count"]):
                    raise ValueError("A2 initializer candidate count differs from frozen bootstrap")
                for candidate in candidates:
                    a2_domain.validate_candidate(candidate)
                    execution_domain.validate_candidate(candidate)
                evidence_ref = str(result["evidence_ref"])
                if not evidence_ref.startswith("runtime-artifact:"):
                    raise ValueError("A2 initializer lacks Runtime artifact evidence")
            except (KeyError, TypeError, ValueError) as exc:
                return self._fail(checkpoint, f"A2 initializer artifact is invalid: {exc}")
            checkpoint = self._save(checkpoint, {
                **state, "bootstrap_candidate_values": candidates,
                "bootstrap_candidates": [], "policy_evidence_ref": evidence_ref,
                "status": "bootstrap_candidates_pending"})
            return self._submit_candidates(checkpoint, role="bootstrap")

        if status == "bootstrap_candidates_pending":
            return self._submit_candidates(checkpoint, role="bootstrap")

        if status == "bootstrap_candidates_running":
            run_ids = [item["run_id"] for item in state["bootstrap_candidates"]]
            self._execute(run_ids, execute, max_parallel)
            if not self._all_terminal(run_ids):
                return self.checkpoints.get(pipeline_id)
            observed = self._observe(
                state["bootstrap_candidates"], state, a2_domain)
            usable = sum(item.get("status") == "succeeded" and bool(item.get("metrics"))
                         for item in [*state["observations"], *observed])
            state = {**state, "bootstrap_observations": observed,
                     "observations": [*state["observations"], *observed],
                     "measured_observations": [*state["measured_observations"], *observed],
                     "status": "policy_pending"}
            checkpoint = self._save(checkpoint, state)
            required = int(a2_domain.experiment_protocol["budget"]
                           ["minimum_successful_observations"])
            if usable < required:
                return self._diagnosis(
                    checkpoint, "native bootstrap produced insufficient measured feedback")
            return checkpoint

        if status == "policy_pending":
            step = int(state["feedback_step"])
            capability = ("optimizer.l2.a2-orfo-policy" if step == 0
                          else "optimizer.l2.a2-orfo-feedback")
            task = build_a2_orfo_policy_task(
                project_id=self._project_id(state), design_id=a2_domain.design,
                objective=state["objective"], observations=state["observations"],
                domain=a2_domain, n_suggestions=int(state["n_suggestions"]),
                optimizer_seed=int(state["optimizer_seeds"][step]),
                prior_checkpoint=state.get("policy_checkpoint"),
                task_id=f"{pipeline_id}-a2-policy-{step}")
            run = self.runtime.submit_idempotent(task, capability=capability)
            return self._save(checkpoint, {
                **state, "policy_run_id": run.run_id,
                "policy_capability": capability, "status": "policy_running"})

        if status == "policy_running":
            run_id = str(state["policy_run_id"])
            self._execute((run_id,), execute, 1)
            if not self._all_terminal((run_id,)):
                return self.checkpoints.get(pipeline_id)
            if self.runtime_store.get_run(run_id).status.value != "succeeded":
                return self._fail(checkpoint, "A2-ORFO policy Runtime task failed")
            try:
                result = dict(self.policy_result_for_run(run_id))
                candidates = [dict(item) for item in result["candidates"]]
                if len(candidates) != int(state["n_suggestions"]):
                    raise ValueError("A2 policy candidate count differs from frozen request")
                for candidate in candidates:
                    a2_domain.validate_candidate(candidate)
                    execution_domain.validate_candidate(candidate)
                prior = result["checkpoint"]
                # The next TaskSpec builder performs its cryptographic validation;
                # require the exact public envelope before persisting it.
                if not isinstance(prior, Mapping) or set(prior) != {
                        "schema_version", "optimized_prompts", "sha256"}:
                    raise ValueError("A2 policy checkpoint envelope is malformed")
                evidence_ref = str(result["evidence_ref"])
                if not evidence_ref.startswith("runtime-artifact:"):
                    raise ValueError("A2 policy result lacks Runtime artifact evidence")
            except (KeyError, TypeError, ValueError) as exc:
                return self._fail(checkpoint, f"A2 policy artifact is invalid: {exc}")
            state = {**state, "policy_checkpoint": dict(prior),
                     "policy_evidence_ref": evidence_ref,
                     "active_candidate_values": candidates,
                     "active_candidates": []}
            if int(state["feedback_step"]) == feedback_steps:
                state.update({"final_next_candidates": candidates,
                              "status": "confirmation_pending"})
                checkpoint = self._save(checkpoint, state)
                return self._submit_confirmations(checkpoint)
            state["status"] = "candidates_pending"
            checkpoint = self._save(checkpoint, state)
            return self._submit_candidates(checkpoint, role="feedback")

        if status == "candidates_pending":
            return self._submit_candidates(checkpoint, role="feedback")

        if status == "candidates_running":
            run_ids = [item["run_id"] for item in state["active_candidates"]]
            self._execute(run_ids, execute, max_parallel)
            if not self._all_terminal(run_ids):
                return self.checkpoints.get(pipeline_id)
            observed = self._observe(state["active_candidates"], state, a2_domain)
            step = int(state["feedback_step"])
            iteration = {
                "feedback_step": step, "policy_run_id": state["policy_run_id"],
                "policy_capability": state["policy_capability"],
                "candidates": state["active_candidates"],
                "terminal_observations": observed,
            }
            state = {**state,
                     "observations": [*state["observations"], *observed],
                     "measured_observations": [*state["measured_observations"], *observed],
                     "iterations": [*state["iterations"], iteration],
                     "feedback_step": step + 1, "policy_run_id": None,
                     "active_candidates": [], "status": "policy_pending"}
            return self._save(checkpoint, state)

        if status == "confirmation_pending":
            return self._submit_confirmations(checkpoint)

        if status == "confirmation_running":
            run_ids = [item["run_id"] for item in state["confirmation_runs"]]
            self._execute(run_ids, execute, max_parallel)
            if not self._all_terminal(run_ids):
                return self.checkpoints.get(pipeline_id)
            observed = self._observe(state["confirmation_runs"], state, a2_domain)
            usable = [item for item in observed if self._usable(item, state["objective"])]
            return self._save(checkpoint, {
                **state, "confirmation_observations": observed,
                "status": "completed" if len(usable) == len(run_ids)
                else "diagnosis_required",
                "completion_reason": (
                    "a2_feedback_budget_and_confirmations_completed"
                    if len(usable) == len(run_ids)
                    else "one_or_more_confirmations_lacked_canonical_evidence")})

        return self._fail(checkpoint, f"unsupported A2 campaign state: {status}")

    def _submit_candidates(self, checkpoint, *, role):
        state = dict(checkpoint["state"])
        domain = ORFSAgentFullDomain.from_dict(state["execution_domain"])
        if role not in {"bootstrap", "feedback"}:
            raise ValueError("A2 candidate role is invalid")
        values_key = ("bootstrap_candidate_values" if role == "bootstrap"
                      else "active_candidate_values")
        runs_key = "bootstrap_candidates" if role == "bootstrap" else "active_candidates"
        runs = list(state.get(runs_key) or ())
        for index in range(len(runs), len(state[values_key])):
            candidate = dict(state[values_key][index])
            prefix = "a2-bootstrap" if role == "bootstrap" else \
                f"a2-step-{state['feedback_step']}"
            task = build_orfs_agent_full_candidate_task(
                project_id=self._project_id(state), design_id=domain.design,
                objective=state["objective"], domain=domain, candidate=candidate,
                or_seed=int(state["or_seed"]),
                proposal_origin=f"external:A2-ORFO@{A2_ORFO_UPSTREAM_COMMIT}",
                proposal_evidence_refs=(state["policy_evidence_ref"],),
                task_id=f"{checkpoint['pipeline_id']}-{prefix}-candidate-{index}")
            run = self.runtime.submit_idempotent(
                task, capability="optimizer.l2.upstream-full-candidate")
            runs.append({"candidate": candidate, "run_id": run.run_id,
                         "or_seed": int(state["or_seed"])})
            state[runs_key] = runs
            checkpoint = self._save(checkpoint, state)
        return self._save(checkpoint, {**checkpoint["state"],
                                      "status": ("bootstrap_candidates_running"
                                                 if role == "bootstrap" else
                                                 "candidates_running")})

    def _submit_confirmations(self, checkpoint):
        state = dict(checkpoint["state"])
        seeds = list(state["confirmation_seeds"])
        if not seeds:
            return self._save(checkpoint, {
                **state, "status": "completed",
                "completion_reason": "a2_feedback_budget_completed_no_confirmations"})
        incumbent = self._incumbent(state["observations"], state["objective"])
        if incumbent is None:
            return self._diagnosis(checkpoint, "A2 campaign has no measured incumbent")
        domain = ORFSAgentFullDomain.from_dict(state["execution_domain"])
        runs = list(state.get("confirmation_runs") or ())
        for index in range(len(runs), len(seeds)):
            task = build_orfs_agent_full_candidate_task(
                project_id=self._project_id(state), design_id=domain.design,
                objective=state["objective"], domain=domain,
                candidate=incumbent["candidate"], or_seed=int(seeds[index]),
                proposal_origin=f"external:A2-ORFO@{A2_ORFO_UPSTREAM_COMMIT}",
                proposal_evidence_refs=tuple(incumbent["artifact_refs"]),
                task_id=f"{checkpoint['pipeline_id']}-confirmation-{index}")
            run = self.runtime.submit_idempotent(
                task, capability="optimizer.l2.upstream-full-candidate")
            runs.append({"candidate": incumbent["candidate"], "run_id": run.run_id,
                         "or_seed": int(seeds[index])})
            state.update({"incumbent": incumbent, "confirmation_runs": runs})
            checkpoint = self._save(checkpoint, state)
        return self._save(checkpoint, {**checkpoint["state"],
                                      "status": "confirmation_running"})

    def _observe(self, runs, state, a2_domain):
        rows = []
        for item in runs:
            run_id = str(item["run_id"])
            try:
                row = dict(self.observation_for_run(run_id, state))
                row.setdefault("run_id", run_id)
                row.setdefault("candidate", dict(item["candidate"]))
                row["source_protocol_sha256"] = row.get("protocol_sha256")
                row["protocol_sha256"] = a2_domain.protocol_sha256
                row.setdefault("artifact_refs", [])
                a2_domain.validate_observation(row)
            except (OSError, KeyError, TypeError, ValueError) as exc:
                row = {
                    "run_id": run_id, "observation_id": f"unreadable-{run_id}",
                    "status": self.runtime_store.get_run(run_id).status.value,
                    "candidate": dict(item["candidate"]), "metrics": {},
                    "protocol_sha256": a2_domain.protocol_sha256,
                    "artifact_refs": [f"run:{run_id}"], "feasible": False,
                    "failure_category": f"evidence_error:{type(exc).__name__}",
                    "failure_message": str(exc),
                }
            rows.append(row)
        return rows

    @staticmethod
    def _usable(row, objective):
        key = {"ECP": "ECP_final", "DWL": "detailedroute__route__wirelength",
               "COMBO": "Fractional_Loss_final"}[objective]
        return (row.get("status") == "succeeded" and bool(row.get("artifact_refs"))
                and isinstance((row.get("metrics") or {}).get(key), (int, float)))

    @classmethod
    def _incumbent(cls, rows, objective):
        eligible = [row for row in rows if cls._usable(row, objective)]
        if not eligible:
            return None
        key = {"ECP": "ECP_final", "DWL": "detailedroute__route__wirelength",
               "COMBO": "Fractional_Loss_final"}[objective]
        return dict(min(eligible, key=lambda row: float(row["metrics"][key])))

    def _execute(self, run_ids, execute, max_parallel):
        if not execute:
            return
        ready = [run_id for run_id in run_ids
                 if self.runtime_store.get_run(run_id).status.value in {
                     "queued", "retry_wait"}]
        with ThreadPoolExecutor(max_workers=max(1, min(max_parallel, len(ready) or 1))) as pool:
            futures = [pool.submit(self.runtime.execute_once, run_id) for run_id in ready]
            for future in as_completed(futures):
                future.result()

    def _all_terminal(self, run_ids):
        return bool(run_ids) and all(
            self.runtime_store.get_run(run_id).status.value in TERMINAL
            for run_id in run_ids)

    def _checkpoint(self, pipeline_id):
        checkpoint = self.checkpoints.get(pipeline_id)
        if checkpoint["pipeline_kind"] != A2_ORFO_CAMPAIGN_KIND:
            raise KeyError(pipeline_id)
        return checkpoint

    @staticmethod
    def _project_id(state):
        goal = state.get("goal")
        if not isinstance(goal, Mapping) or not isinstance(goal.get("project_id"), str):
            raise ValueError("A2 campaign lacks its authorized Goal")
        return goal["project_id"]

    @staticmethod
    def _fingerprint(*values):
        serialized = []
        for value in values:
            if hasattr(value, "to_dict"):
                value = value.to_dict()
            elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                value = list(value)
            serialized.append(value)
        return hashlib.sha256(json.dumps(
            serialized, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def _save(self, checkpoint, state):
        return self.checkpoints.save(
            checkpoint["pipeline_id"], state,
            expected_revision=int(checkpoint["revision"]))

    def _fail(self, checkpoint, reason):
        return self._save(checkpoint, {**checkpoint["state"], "status": "failed",
                                      "failure": reason})

    def _diagnosis(self, checkpoint, reason):
        return self._save(checkpoint, {
            **checkpoint["state"], "status": "diagnosis_required",
            "diagnosis": {"reason": reason,
                          "boundary": "L3/L4 actions remain outside L2"}})
