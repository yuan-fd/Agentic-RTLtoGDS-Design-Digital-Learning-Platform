"""Durable orchestration for an admitted external L2 optimiser.

This is deliberately a small application service.  It does not contain a
Bayesian optimiser, OpenROAD parser, LLM prompt, or shell command.  Those
belong respectively to the admitted optimiser plugin, the Runtime evidence
exporter, the managed model boundary, and the Runtime adapter.  Keeping this
boundary small is the essential part of the v2 rebuild: the platform owns
protocol and evidence, while a pinned upstream project owns its algorithm.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Mapping, Sequence

from openroad_platform_contracts.platform import TaskSpec


EXTERNAL_L2_KIND = "external-optimizer-loop-v1"
TERMINAL = frozenset({"succeeded", "failed", "cancelled", "timed_out", "lost"})
PAPER_PROTOCOLS = frozenset({"paper_comparable_external_l2_v1",
                             "target_calibrated_external_l2_v2",
                             "target_execution_envelope_external_l2_v3"})


class ExternalOptimizerLoopService:
    """Coordinate an external optimiser without reimplementing it in-tree.

    Callbacks are injected by the HTTP application because it alone knows
    product ownership and how to resolve registered RTL.  The generic loop is
    therefore reusable for other admissible optimiser plugins, and all state
    is a JSON checkpoint that can be audited or resumed after a process exit.
    """

    def __init__(
        self,
        *,
        checkpoints: Any,
        runtime: Any,
        runtime_store: Any,
        observation_for_run: Callable[[str, Mapping[str, Any]], Mapping[str, Any]],
        optimizer_task: Callable[[Sequence[Mapping[str, Any]], Mapping[str, Any]], TaskSpec],
        candidates_for_run: Callable[[str], Sequence[Mapping[str, Any]]],
    ) -> None:
        self.checkpoints = checkpoints
        self.runtime = runtime
        self.runtime_store = runtime_store
        self.observation_for_run = observation_for_run
        self.optimizer_task = optimizer_task
        self.candidates_for_run = candidates_for_run

    @staticmethod
    def _fingerprint(state: Mapping[str, Any]) -> str:
        frozen = {
            name: state[name] for name in (
                "design_id", "platform", "objective_profile", "base_task",
                "baseline_parameters", "replica_or_seeds", "max_candidates",
                "candidates_per_round", "minimum_relative_improvement",
                "frozen_constraints", "optimizer_plugin",
            )
        }
        # A performance campaign is not defined by its optimiser alone.  The
        # initial observations, seeds and confirmation policy determine what
        # the GP is allowed to learn and how a claimed winner is measured.
        # Keep these in the immutable protocol receipt as well.  ``get``
        # deliberately preserves the older, explicitly-labelled admission
        # smoke format for historical evidence without allowing it to become
        # the product performance path.
        frozen.update({
            "protocol_mode": state.get("protocol_mode", "admission_smoke"),
            "warmup_recipes": state.get("warmup_recipes", ()),
            "warmup_seed": state.get("warmup_seed"),
            "minimum_distinct_feasible_observations": state.get(
                "minimum_distinct_feasible_observations"),
            "confirmation_seeds": state.get("confirmation_seeds", ()),
            "optimizer_seed": state.get("optimizer_seed"),
            "max_parallel": state.get("max_parallel"),
            "admitted_target_domain": state.get("admitted_target_domain"),
        })
        return hashlib.sha256(json.dumps(
            frozen, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()

    def create(
        self,
        *,
        subject_id: str,
        owner_id: str | None,
        initial_state: Mapping[str, Any],
    ) -> dict[str, Any]:
        state = dict(initial_state)
        self._validate_initial_protocol(state)
        state["protocol_fingerprint"] = self._fingerprint(state)
        checkpoint = self.checkpoints.create_or_get(
            pipeline_kind=EXTERNAL_L2_KIND, subject_id=subject_id,
            owner_id=owner_id, initial_state=state,
        )
        if checkpoint["state"].get("protocol_fingerprint") != state["protocol_fingerprint"]:
            raise ValueError("experiment_key already exists with a different frozen external-optimizer protocol")
        return self._submit_missing_baselines(checkpoint)

    @staticmethod
    def _validate_initial_protocol(state: Mapping[str, Any]) -> None:
        """Reject an under-specified performance campaign before it runs.

        An admission smoke intentionally has a tiny fixed budget and remains
        valid historical evidence.  Every new product/performance campaign,
        however, must keep baseline replicas separate from diverse warm-up
        observations.  This makes the former "three copies of one baseline"
        error impossible to repeat silently.
        """
        mode = str(state.get("protocol_mode", "admission_smoke"))
        if mode == "admission_smoke":
            recipes = state.get("admission_probe_recipes", ())
            if recipes:
                if not isinstance(recipes, list) or len(recipes) < 2:
                    raise ValueError("admission probes require at least two frozen parameter-distinct recipes")
                fingerprints: set[str] = set()
                for index, recipe in enumerate(recipes):
                    if not isinstance(recipe, Mapping) or not isinstance(recipe.get("parameters"), Mapping):
                        raise ValueError(f"admission probe {index} lacks parameters")
                    fingerprint = json.dumps(recipe["parameters"], sort_keys=True, separators=(",", ":"))
                    if fingerprint in fingerprints:
                        raise ValueError("admission probes must be parameter-distinct")
                    fingerprints.add(fingerprint)
            return
        if mode not in PAPER_PROTOCOLS:
            raise ValueError("unsupported external L2 protocol_mode")
        if mode in {"target_calibrated_external_l2_v2", "target_execution_envelope_external_l2_v3"}:
            domain = state.get("admitted_target_domain")
            if not isinstance(domain, Mapping):
                raise ValueError("target-calibrated L2 requires an admitted target domain")
            names, fixed, values = (domain.get("search_parameter_names"),
                                    domain.get("fixed_parameters"),
                                    domain.get("admissible_values"))
            if (not isinstance(names, list) or not names or not isinstance(fixed, Mapping)
                    or not isinstance(values, Mapping) or set(names) != set(values)
                    or set(names) & set(fixed)):
                raise ValueError("admitted target domain is structurally invalid")
            if mode == "target_execution_envelope_external_l2_v3":
                if domain.get("kind") != "target-execution-envelope-v1":
                    raise ValueError("execution-envelope L2 requires a versioned execution envelope")
                if not isinstance(domain.get("verified_values"), Mapping):
                    raise ValueError("execution-envelope L2 requires verified-value evidence")
        recipes = state.get("warmup_recipes")
        if not isinstance(recipes, list) or len(recipes) < 8:
            raise ValueError("paper-comparable L2 requires at least eight frozen warm-up recipes")
        fingerprints: set[str] = set()
        for index, recipe in enumerate(recipes):
            if not isinstance(recipe, Mapping) or not isinstance(recipe.get("parameters"), Mapping):
                raise ValueError(f"warm-up recipe {index} lacks parameters")
            fingerprint = json.dumps(recipe["parameters"], sort_keys=True, separators=(",", ":"))
            if fingerprint in fingerprints:
                raise ValueError("warm-up recipes must be parameter-distinct")
            fingerprints.add(fingerprint)
        minimum = int(state.get("minimum_distinct_feasible_observations") or 0)
        if minimum < 8 or minimum > len(recipes) + 1:
            raise ValueError("minimum distinct feasible observations must be between 8 and warmups + baseline")
        warmup_seed = state.get("warmup_seed")
        if not isinstance(warmup_seed, int) or warmup_seed < 0:
            raise ValueError("paper-comparable L2 requires a non-negative warmup_seed")
        confirmation = state.get("confirmation_seeds")
        if (not isinstance(confirmation, list) or len(confirmation) < 3
                or len(set(confirmation)) != len(confirmation)
                or any(not isinstance(seed, int) or seed < 0 for seed in confirmation)):
            raise ValueError("paper-comparable L2 requires at least three distinct confirmation seeds")
        if int(state.get("candidates_per_round") or 0) < 2:
            raise ValueError("paper-comparable L2 requires at least two candidates per round")

    def advance(
        self,
        pipeline_id: str,
        *,
        execute: bool = False,
        max_parallel: int = 1,
    ) -> dict[str, Any]:
        """Advance exactly one durable transition family.

        ``execute=False`` is suitable for the HTTP boundary: it only records
        work.  The controller worker calls it with ``execute=True`` and is the
        only component that waits for an EDA tool.  A browser never gets a
        shell-equivalent ability through this method.
        """
        checkpoint = self.checkpoints.get(pipeline_id)
        if checkpoint["pipeline_kind"] != EXTERNAL_L2_KIND:
            raise KeyError(pipeline_id)
        state = checkpoint["state"]
        status = str(state.get("status"))
        if status in {"completed", "diagnosis_required", "failed"}:
            return checkpoint

        if status == "baseline_running":
            checkpoint = self._submit_missing_baselines(checkpoint)
            state = checkpoint["state"]
            self._execute_if_requested(state.get("baseline_run_ids", ()), execute, max_parallel)
            if not self._all_terminal(state.get("baseline_run_ids", ())):
                return self.checkpoints.get(pipeline_id)
            observations = self._observations(state["baseline_run_ids"], state)
            usable = [item for item in observations if self._usable(item)]
            if len(usable) < 2:
                return self._fail(checkpoint, "baseline did not produce two usable Runtime observations")
            baseline = self._median_metrics(usable)
            scored = [self._with_objective(item, baseline, state["objective_profile"])
                      for item in usable]
            # A baseline is a distribution, not its luckiest replica.  The
            # frozen reference used for every acceptance comparison is its
            # median objective, matching the metric medians above.
            baseline_objective = self._median(
                [item["metrics"]["optimizer_objective"] for item in scored]
            )
            next_status = ("warmup_running" if state.get("protocol_mode") in PAPER_PROTOCOLS
                           else "admission_probe_running" if state.get("admission_probe_recipes")
                           else "optimizer_pending")
            state.update({
                "baseline_observations": scored,
                "baseline_metrics": baseline,
                # Repeated baselines measure noise.  They must not appear as
                # duplicated training coordinates in the upstream GP data.
                "observations": scored,
                "optimizer_observations": [scored[0]],
                "baseline_objective": baseline_objective,
                "best_objective": baseline_objective,
                "best_configuration": "baseline",
                "status": next_status,
                "agent_events": [*state.get("agent_events", []), {
                    "phase": "observe", "claim": "recorded repeated, immutable Runtime baseline evidence",
                    "run_ids": list(state["baseline_run_ids"]), "execution_allowed": False,
                }],
            })
            return self._save(checkpoint, state)

        if status == "warmup_running":
            checkpoint = self._submit_missing_warmups(checkpoint)
            state = checkpoint["state"]
            warmup_ids = [str(item["run_id"]) for item in state.get("warmup_runs", [])]
            self._execute_if_requested(warmup_ids, execute, max_parallel)
            if not self._all_terminal(warmup_ids):
                return self.checkpoints.get(pipeline_id)
            return self._finish_warmup(checkpoint)

        if status == "admission_probe_running":
            checkpoint = self._submit_missing_admission_probes(checkpoint)
            state = checkpoint["state"]
            probe_ids = [str(item["run_id"]) for item in state.get("admission_probe_runs", [])]
            self._execute_if_requested(probe_ids, execute, max_parallel)
            if not self._all_terminal(probe_ids):
                return self.checkpoints.get(pipeline_id)
            return self._finish_admission_probes(checkpoint)

        if status == "optimizer_pending":
            return self._submit_optimizer(checkpoint)

        if status == "optimizer_running":
            run_id = str(state["optimizer_run_id"])
            self._execute_if_requested((run_id,), execute, 1)
            if not self._all_terminal((run_id,)):
                return self.checkpoints.get(pipeline_id)
            run = self.runtime_store.get_run(run_id)
            if run.status.value != "succeeded":
                return self._fail(checkpoint, "external optimiser Runtime task failed")
            try:
                candidates = list(self.candidates_for_run(run_id))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                return self._fail(checkpoint, f"external optimiser candidate artifact is invalid: {exc}")
            if not candidates:
                return self._fail(checkpoint, "external optimiser produced no candidates")
            return self._submit_candidates(checkpoint, candidates)

        if status == "candidate_running":
            active = list(state.get("active_candidates") or [])
            run_ids = [run_id for item in active for run_id in item.get("run_ids", [])]
            self._execute_if_requested(run_ids, execute, max_parallel)
            if not self._all_terminal(run_ids):
                return self.checkpoints.get(pipeline_id)
            return self._finish_candidate_round(checkpoint)

        if status == "confirmation_running":
            run_ids = list(state.get("confirmation_run_ids") or [])
            self._execute_if_requested(run_ids, execute, max_parallel)
            if not self._all_terminal(run_ids):
                return self.checkpoints.get(pipeline_id)
            return self._finish_confirmation(checkpoint)

        return self._fail(checkpoint, f"unsupported external optimiser state: {status}")

    def _submit_missing_baselines(self, checkpoint: Mapping[str, Any]) -> dict[str, Any]:
        state = dict(checkpoint["state"])
        run_ids = list(state.get("baseline_run_ids") or [])
        base = TaskSpec.from_dict(state["base_task"])
        for replica_index in range(len(run_ids), len(state["replica_or_seeds"])):
            task = dataclasses.replace(
                base,
                task_id=f"{checkpoint['pipeline_id']}-baseline-r{replica_index}",
                parameters={**base.parameters, "or_seed": state["replica_or_seeds"][replica_index]},
                labels={**base.labels, "external_l2_pipeline_id": checkpoint["pipeline_id"],
                        "external_l2_role": "baseline", "replica_index": str(replica_index)},
            )
            run_ids.append(self.runtime.submit(task).run_id)
            state["baseline_run_ids"] = run_ids
            checkpoint = self._save(checkpoint, state)
        return dict(checkpoint)

    def _submit_missing_warmups(self, checkpoint: Mapping[str, Any]) -> dict[str, Any]:
        """Schedule the frozen upstream-style initial observations.

        This is a data-collection step, not a platform BO implementation: the
        recipes are part of the frozen campaign protocol and the next numeric
        candidates still come solely from the pinned ORFS-Agent GP/EI.
        """
        state = dict(checkpoint["state"])
        base = TaskSpec.from_dict(state["base_task"])
        runs = list(state.get("warmup_runs") or [])
        recipes = list(state.get("warmup_recipes") or [])
        for index in range(len(runs), len(recipes)):
            recipe = dict(recipes[index])
            proposed = recipe.get("parameters")
            if not isinstance(proposed, Mapping):
                return self._fail(checkpoint, f"warm-up recipe {index} lacks parameters")
            effective = {**state["baseline_parameters"], **dict(proposed)}
            task = dataclasses.replace(
                base,
                task_id=f"{checkpoint['pipeline_id']}-warmup-{index}",
                parameters={**base.parameters, "flow_parameters": effective,
                            "or_seed": int(state["warmup_seed"])},
                labels={**base.labels, "external_l2_pipeline_id": checkpoint["pipeline_id"],
                        "external_l2_role": "warmup", "warmup_id": str(recipe.get("recipe_id") or index)},
            )
            run_id = self.runtime.submit(task).run_id
            runs.append({"recipe": recipe, "effective_parameters": effective, "run_id": run_id})
            state["warmup_runs"] = runs
            checkpoint = self._save(checkpoint, state)
        return dict(checkpoint)

    def _submit_missing_admission_probes(self, checkpoint: Mapping[str, Any]) -> dict[str, Any]:
        """Collect distinct, frozen points needed to exercise an upstream GP/EI smoke.

        These probes exist only for a bounded integration admission.  They are
        not repeated baselines and never support a performance claim.
        """
        state = dict(checkpoint["state"])
        base = TaskSpec.from_dict(state["base_task"])
        runs = list(state.get("admission_probe_runs") or [])
        recipes = list(state.get("admission_probe_recipes") or [])
        for index in range(len(runs), len(recipes)):
            recipe = dict(recipes[index])
            proposed = recipe.get("parameters")
            if not isinstance(proposed, Mapping):
                return self._fail(checkpoint, f"admission probe {index} lacks parameters")
            effective = {**state["baseline_parameters"], **dict(proposed)}
            task = dataclasses.replace(
                base,
                task_id=f"{checkpoint['pipeline_id']}-admission-probe-{index}",
                parameters={**base.parameters, "flow_parameters": effective,
                            "or_seed": int(state["replica_or_seeds"][0])},
                labels={**base.labels, "external_l2_pipeline_id": checkpoint["pipeline_id"],
                        "external_l2_role": "admission_probe", "admission_probe_id": str(recipe.get("recipe_id") or index)},
            )
            runs.append({"recipe": recipe, "effective_parameters": effective,
                         "run_id": self.runtime.submit(task).run_id})
            state["admission_probe_runs"] = runs
            checkpoint = self._save(checkpoint, state)
        return dict(checkpoint)

    def _finish_admission_probes(self, checkpoint: Mapping[str, Any]) -> dict[str, Any]:
        state = dict(checkpoint["state"])
        probes = self._observations(
            [str(item["run_id"]) for item in state.get("admission_probe_runs", [])], state,
        )
        usable = [self._with_objective(item, state["baseline_metrics"], state["objective_profile"])
                  for item in probes if self._usable(item)]
        training = self._distinct_parameter_rows([
            *state.get("optimizer_observations", [])[:1], *usable,
        ])
        if len(training) < 2:
            return self._fail(checkpoint, "admission probes did not produce two distinct usable Runtime observations")
        state.update({"admission_probe_observations": probes, "optimizer_observations": training,
                      "observations": [*state.get("observations", []), *usable],
                      "status": "optimizer_pending"})
        state.setdefault("agent_events", []).append({
            "phase": "observe",
            "claim": "recorded frozen, parameter-distinct admission probes for upstream GP/EI interoperability",
            "probe_run_ids": [str(item["run_id"]) for item in state.get("admission_probe_runs", [])],
            "execution_allowed": False,
        })
        return self._save(checkpoint, state)

    def _finish_warmup(self, checkpoint: Mapping[str, Any]) -> dict[str, Any]:
        state = dict(checkpoint["state"])
        terminal: list[dict[str, Any]] = []
        usable: list[dict[str, Any]] = []
        for item in state.get("warmup_runs", []):
            row = self._observations((item["run_id"],), state)[0]
            recorded = (self._with_objective(row, state["baseline_metrics"], state["objective_profile"])
                        if self._usable(row) else row)
            terminal.append({**item, "observation": recorded})
            if self._usable(row):
                usable.append(recorded)
        # One baseline coordinate is included as the control point; replicas
        # remain exclusively in baseline_observations for variance reporting.
        training = [*state.get("optimizer_observations", [])[:1], *usable]
        distinct = self._distinct_parameter_rows(training)
        state.update({
            "warmup_terminal_observations": terminal,
            "warmup_usable_observations": usable,
            "optimizer_observations": distinct,
            "observations": [*state.get("observations", []), *usable],
        })
        minimum = int(state["minimum_distinct_feasible_observations"])
        if len(distinct) < minimum:
            return self._fail(
                checkpoint,
                f"warm-up yielded {len(distinct)} distinct feasible observations; protocol requires {minimum}",
            )
        state["status"] = "optimizer_pending"
        state.setdefault("agent_events", []).append({
            "phase": "observe",
            "claim": "completed frozen diverse warm-up; only distinct feasible Runtime observations can train upstream GP/EI",
            "warmup_count": len(terminal), "distinct_feasible_count": len(distinct),
            "execution_allowed": False,
        })
        return self._save(checkpoint, state)

    def _submit_optimizer(self, checkpoint: Mapping[str, Any]) -> dict[str, Any]:
        state = dict(checkpoint["state"])
        observations = state.get("optimizer_observations", state["observations"])
        task = self.optimizer_task(observations, state)
        task = dataclasses.replace(
            task, task_id=f"{checkpoint['pipeline_id']}-optimizer-{state['round']}",
            labels={**task.labels, "external_l2_pipeline_id": checkpoint["pipeline_id"],
                    "external_l2_role": "optimizer"},
        )
        state.update({"optimizer_run_id": self.runtime.submit(task).run_id,
                      "status": "optimizer_running"})
        state.setdefault("agent_events", []).append({
            "phase": "hypothesis",
            "claim": str(state.get(
                "optimizer_event_claim",
                "admitted optimiser proposes only allowlisted physical-design vectors",
            )),
            "execution_allowed": False,
        })
        return self._save(checkpoint, state)

    def _submit_candidates(self, checkpoint: Mapping[str, Any],
                           candidates: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        state = dict(checkpoint["state"])
        remaining = int(state["max_candidates"]) - int(state.get("candidate_count") or 0)
        selected = list(candidates)[:max(0, min(remaining, int(state["candidates_per_round"])))]
        if not selected:
            state["status"] = "completed"
            state["completion_reason"] = "fixed_candidate_budget_exhausted"
            return self._save(checkpoint, state)
        base = TaskSpec.from_dict(state["base_task"])
        # Re-running an already-screened coordinate as a new candidate would
        # spend budget without collecting a new point.  That is particularly
        # misleading when comparing GP/EI with a non-adaptive control.  Do
        # not silently drop, resample, or relabel it: fail the frozen campaign
        # and retain the adapter proposal artifact for diagnosis.
        seen_effective: dict[str, str] = {}

        def remember(parameters: Mapping[str, Any], source: str) -> None:
            fingerprint = json.dumps(parameters, sort_keys=True, separators=(",", ":"), default=str)
            seen_effective.setdefault(fingerprint, source)

        remember(state["baseline_parameters"], "baseline")
        for warmup in state.get("warmup_runs", []):
            if isinstance(warmup, Mapping) and isinstance(warmup.get("effective_parameters"), Mapping):
                remember(warmup["effective_parameters"], "warmup")
        for round_item in state.get("history", []):
            if not isinstance(round_item, Mapping):
                continue
            for result in round_item.get("results", []):
                if isinstance(result, Mapping) and isinstance(result.get("effective_parameters"), Mapping):
                    remember(result["effective_parameters"], "prior_candidate")
        # Validate the entire batch before submitting a single Runtime task.
        # A prior implementation submitted early candidates then discovered a
        # later duplicate, leaving a misleading queued prefix.  Submission is
        # now atomic with respect to validation failures.
        validated: list[tuple[Mapping[str, Any], dict[str, Any]]] = []
        for index, candidate in enumerate(selected):
            proposed = candidate.get("platform_parameters")
            if not isinstance(proposed, Mapping):
                return self._fail(checkpoint, "external optimiser candidate lacks platform_parameters")
            # Parameters outside the admitted intersection remain at the
            # server-owned baseline.  This is an explicit fairness boundary.
            effective = {**state["baseline_parameters"], **dict(proposed)}
            fingerprint = json.dumps(effective, sort_keys=True, separators=(",", ":"), default=str)
            prior = seen_effective.get(fingerprint)
            if prior is not None:
                return self._fail(
                    checkpoint,
                    f"optimizer proposed duplicate effective parameter vector already used by {prior}",
                )
            seen_effective[fingerprint] = f"candidate_{index}"
            validated.append((candidate, effective))

        active = []
        for index, (candidate, effective) in enumerate(validated):
            # Screening a large upstream batch once is how the official
            # campaign obtains information economically.  Only its selected
            # incumbent is re-run with the independent confirmation seeds.
            screening_seeds = ([int(state["warmup_seed"])]
                               if state.get("protocol_mode") in PAPER_PROTOCOLS
                               else list(state["replica_or_seeds"]))
            run_ids = []
            for replica_index, seed in enumerate(screening_seeds):
                task = dataclasses.replace(
                    base,
                    task_id=f"{checkpoint['pipeline_id']}-r{state['round']}-c{index}-p{replica_index}",
                    parameters={**base.parameters, "flow_parameters": effective, "or_seed": seed},
                    labels={**base.labels, "external_l2_pipeline_id": checkpoint["pipeline_id"],
                            "external_l2_role": "candidate", "candidate_id": str(candidate.get("candidate_id") or index),
                            "replica_index": str(replica_index)},
                )
                run_ids.append(self.runtime.submit(task).run_id)
            active.append({"candidate": dict(candidate), "effective_parameters": effective,
                           "run_ids": run_ids})
        state.update({"active_candidates": active, "status": "candidate_running"})
        return self._save(checkpoint, state)

    def _finish_candidate_round(self, checkpoint: Mapping[str, Any]) -> dict[str, Any]:
        state = dict(checkpoint["state"])
        results = []
        all_observations = list(state["observations"])
        optimizer_observations = list(state.get("optimizer_observations", state["observations"]))
        for item in state.get("active_candidates", []):
            observed = self._observations(item["run_ids"], state)
            # Preserve every terminal receipt in the history, including
            # infeasible and failed replicas.  Only complete, feasible rows
            # train the upstream GP/EI; hiding failures from the dashboard or
            # audit trail would make an unsuccessful candidate look absent.
            scored_by_run = {
                row["run_id"]: self._with_objective(
                    row, state["baseline_metrics"], state["objective_profile"])
                for row in observed if self._usable(row)
            }
            scored = list(scored_by_run.values())
            recorded = [scored_by_run.get(row.get("run_id"), row) for row in observed]
            all_observations.extend(scored)
            optimizer_observations.extend(scored)
            values = [row["metrics"]["optimizer_objective"] for row in scored]
            results.append({**item, "observations": scored,
                            "terminal_observations": recorded,
                            "objective_median": self._median(values) if values else None,
                            "eligible": len(scored) == len(item["run_ids"])})
        previous = float(state["best_objective"])
        best = min((item for item in results if item["eligible"] and item["objective_median"] is not None),
                   key=lambda item: float(item["objective_median"]), default=None)
        improved = bool(best is not None and self._materially_improved(
            float(best["objective_median"]), previous, float(state["minimum_relative_improvement"])))
        if improved:
            state["best_objective"] = float(best["objective_median"])
            state["best_configuration"] = str(best["candidate"].get("candidate_id"))
            state["stalled_rounds"] = 0
        else:
            state["stalled_rounds"] = int(state.get("stalled_rounds") or 0) + 1
        state["candidate_count"] = int(state.get("candidate_count") or 0) + len(results)
        state["round"] = int(state.get("round") or 0) + 1
        state["observations"] = all_observations
        state["optimizer_observations"] = self._distinct_parameter_rows(optimizer_observations)
        state.setdefault("history", []).append({"round": state["round"], "results": results,
                                                  "improved": improved, "best_objective": state["best_objective"]})
        state["active_candidates"] = []
        state.setdefault("agent_events", []).extend((
            {"phase": "validate", "claim": "recorded candidate QoR only from terminal Runtime evidence",
             "execution_allowed": False},
            {"phase": "review", "claim": "candidate accepted only after repeated measurement and fixed objective comparison",
             "improved": improved, "execution_allowed": False},
        ))
        # A product loop may hand off after a bounded stagnation window.  A
        # preregistered equal-budget experiment must instead consume its
        # complete fixed budget in every arm; otherwise the arm that happens
        # to stall first receives fewer measurements and is not comparable.
        if state["stalled_rounds"] >= 3 and bool(state.get("allow_stagnation_handoff", True)):
            state.update({"status": "diagnosis_required",
                          "completion_reason": "three_consecutive_non_improving_rounds",
                          "diagnosis": {"next": "repair-agent", "boundary": "L3/L4 actions are not admitted in this L2 loop"}})
        elif state["candidate_count"] >= state["max_candidates"]:
            if (state.get("protocol_mode") in PAPER_PROTOCOLS
                    and state.get("best_configuration") != "baseline"):
                return self._submit_confirmation(checkpoint, state)
            state.update({"status": "completed", "completion_reason": "fixed_candidate_budget_exhausted"})
        else:
            state["status"] = "optimizer_pending"
        return self._save(checkpoint, state)

    def _submit_confirmation(self, checkpoint: Mapping[str, Any], state: Mapping[str, Any]) -> dict[str, Any]:
        """Re-run the screened winner under independent frozen seeds."""
        winning: Mapping[str, Any] | None = None
        for round_item in reversed(state.get("history", [])):
            for result in round_item.get("results", []):
                if str(result.get("candidate", {}).get("candidate_id")) == str(state["best_configuration"]):
                    winning = result
                    break
            if winning is not None:
                break
        if winning is None:
            return self._fail(checkpoint, "screened incumbent is absent from candidate history")
        base = TaskSpec.from_dict(state["base_task"])
        run_ids: list[str] = []
        for replica_index, seed in enumerate(state["confirmation_seeds"]):
            task = dataclasses.replace(
                base,
                task_id=f"{checkpoint['pipeline_id']}-confirm-{replica_index}",
                parameters={**base.parameters, "flow_parameters": winning["effective_parameters"], "or_seed": seed},
                labels={**base.labels, "external_l2_pipeline_id": checkpoint["pipeline_id"],
                        "external_l2_role": "confirmation",
                        "candidate_id": str(state["best_configuration"]),
                        "replica_index": str(replica_index)},
            )
            run_ids.append(self.runtime.submit(task).run_id)
        state.update({"confirmation_candidate": dict(winning), "confirmation_run_ids": run_ids,
                      "status": "confirmation_running"})
        return self._save(checkpoint, state)

    def _finish_confirmation(self, checkpoint: Mapping[str, Any]) -> dict[str, Any]:
        state = dict(checkpoint["state"])
        observed = self._observations(state.get("confirmation_run_ids", ()), state)
        scored = [self._with_objective(row, state["baseline_metrics"], state["objective_profile"])
                  for row in observed if self._usable(row)]
        values = [float(row["metrics"]["optimizer_objective"]) for row in scored]
        median = self._median(values) if values else None
        confirmed = bool(
            len(scored) == len(state.get("confirmation_seeds", ())) and median is not None
            and self._materially_improved(float(median), float(state["baseline_objective"]),
                                           float(state["minimum_relative_improvement"]))
        )
        state.update({
            "final_confirmation": {"candidate_id": state["best_configuration"],
                                   "terminal_observations": [*scored, *[row for row in observed if not self._usable(row)]],
                                   "objective_median": median, "confirmed_improvement": confirmed},
            "status": "completed",
            "completion_reason": ("candidate_confirmed_after_independent_repetitions"
                                  if confirmed else "screened_candidate_not_confirmed"),
        })
        if not confirmed:
            state["best_configuration"] = "baseline"
            state["best_objective"] = float(state["baseline_objective"])
        return self._save(checkpoint, state)

    def _observations(self, run_ids: Sequence[str], state: Mapping[str, Any]) -> list[dict[str, Any]]:
        rows = []
        for run_id in run_ids:
            try:
                rows.append(dict(self.observation_for_run(run_id, state)))
            except (KeyError, ValueError, OSError) as exc:
                rows.append({"run_id": run_id, "observation_id": f"unreadable-{run_id}",
                             "parameters": {}, "metrics": {}, "artifact_refs": [],
                             "feasible": False, "status": "failed",
                             "failure_category": f"evidence_error:{type(exc).__name__}"})
        return rows

    @staticmethod
    def _distinct_parameter_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        """Keep one measured feasible receipt per parameter coordinate.

        This does not erase replicas from the audit record; it only prevents a
        GP from mistaking repeated measurements of one coordinate for design
        space coverage.
        """
        selected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            parameters = row.get("parameters")
            if not isinstance(parameters, Mapping):
                continue
            fingerprint = json.dumps(parameters, sort_keys=True, separators=(",", ":"), default=str)
            if fingerprint not in seen:
                selected.append(dict(row))
                seen.add(fingerprint)
        return selected

    def _all_terminal(self, run_ids: Sequence[str]) -> bool:
        return bool(run_ids) and all(self.runtime_store.get_run(run_id).status.value in TERMINAL
                                    for run_id in run_ids)

    def _execute_if_requested(self, run_ids: Sequence[str], execute: bool, max_parallel: int) -> None:
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

    @staticmethod
    def _usable(row: Mapping[str, Any]) -> bool:
        metrics = row.get("metrics") or {}
        return (row.get("status") == "succeeded" and bool(row.get("feasible"))
                and all(isinstance(metrics.get(name), (int, float))
                        for name in ("area_um2", "setup_wns_ns", "power_W", "drc_errors")))

    @staticmethod
    def _median(values: Sequence[float]) -> float:
        ordered = sorted(float(value) for value in values)
        if not ordered:
            raise ValueError("median needs a value")
        middle = len(ordered) // 2
        return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2

    def _median_metrics(self, rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
        names = ("area_um2", "setup_wns_ns", "power_W", "drc_errors")
        return {name: self._median([float(row["metrics"][name]) for row in rows]) for name in names}

    @staticmethod
    def _with_objective(row: Mapping[str, Any], baseline: Mapping[str, float], profile: str) -> dict[str, Any]:
        result = {**row, "metrics": dict(row.get("metrics") or {})}
        metric = result["metrics"]
        area = float(metric["area_um2"]) / max(float(baseline["area_um2"]), 1e-9)
        power = float(metric["power_W"]) / max(float(baseline["power_W"]), 1e-12)
        timing = (float(baseline["setup_wns_ns"]) - float(metric["setup_wns_ns"])) / max(
            abs(float(baseline["setup_wns_ns"])), 1.0)
        weights = {
            "area": (1.0, 0.0, 0.0), "power": (0.0, 1.0, 0.0),
            "timing": (0.0, 0.0, 1.0), "performance": (0.0, 0.0, 1.0),
            "balanced": (0.35, 0.25, 0.40),
        }
        if profile not in weights:
            raise ValueError("unknown objective profile")
        wa, wp, wt = weights[profile]
        metric["optimizer_objective"] = wa * area + wp * power + wt * timing
        return result

    @staticmethod
    def _materially_improved(candidate: float, incumbent: float, threshold: float) -> bool:
        return candidate < incumbent - threshold * max(abs(incumbent), 1.0)

    def _save(self, checkpoint: Mapping[str, Any], state: Mapping[str, Any]) -> dict[str, Any]:
        return self.checkpoints.save(checkpoint["pipeline_id"], state,
                                     expected_revision=checkpoint["revision"])

    def _fail(self, checkpoint: Mapping[str, Any], reason: str) -> dict[str, Any]:
        state = dict(checkpoint["state"])
        state.update({"status": "failed", "failure": reason})
        return self._save(checkpoint, state)
