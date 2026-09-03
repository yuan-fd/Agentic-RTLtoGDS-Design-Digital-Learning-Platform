from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from openroad_platform_contracts.platform import TaskSpec
from openroad_platform_scheduler.pipeline_checkpoint import PipelineCheckpointStore

from openroad_platform_scheduler.external_l2_service import (
    EXTERNAL_L2_KIND, ExternalOptimizerLoopService,
)


@dataclass
class _Run:
    run_id: str
    status: object


@dataclass
class _Status:
    value: str


class _Store:
    def __init__(self):
        self.runs: dict[str, _Run] = {}

    def get_run(self, run_id: str):
        return self.runs[run_id]


class _Runtime:
    def __init__(self, store: _Store):
        self.store = store
        self.tasks: list[TaskSpec] = []

    def submit(self, task: TaskSpec):
        run_id = f"run-{len(self.tasks)}"
        self.tasks.append(task)
        self.store.runs[run_id] = _Run(run_id, _Status("queued"))
        return self.store.runs[run_id]

    def execute_once(self, run_id: str):
        self.store.runs[run_id].status = _Status("succeeded")


def _base_task() -> TaskSpec:
    return TaskSpec(
        task_id="base", project_id="project", design_id="gcd", plugin_id="orfs",
        inputs={"rtl": {"path": "/tmp/gcd.v", "size_bytes": 1, "sha256": "0" * 64}},
        parameters={"platform": "nangate45", "target_stage": "finish",
                    "clock_period_ns": 10.0, "flow_parameters": {
                        "core_utilization_pct": 55, "place_density_lb_addon": .2,
                    }},
        timeout_seconds=60, labels={}, expected_artifacts=("report",),
    )


def test_external_l2_loop_is_runtime_evidence_to_external_plugin_to_runtime(tmp_path: Path):
    store, runtime = _Store(), _Runtime(_Store())
    store = runtime.store
    def observation(run_id: str, _state):
        candidate = "external_l2_role" in runtime.tasks[int(run_id.removeprefix("run-"))].labels and \
            runtime.tasks[int(run_id.removeprefix("run-"))].labels["external_l2_role"] == "candidate"
        return {
            "observation_id": f"obs-{run_id}", "run_id": run_id, "status": "succeeded",
            "parameters": {"core_utilization_pct": 55, "place_density_lb_addon": .2,
                           "tns_end_percent": 100, "global_placement_padding": 0,
                           "detail_placement_padding": 0, "enable_dpo": 1,
                           "cts_cluster_size": 20, "cts_cluster_diameter": 90},
            "metrics": {"area_um2": 90.0 if candidate else 100.0,
                        "power_W": 1.0, "setup_wns_ns": .1, "drc_errors": 0.0},
            "artifact_refs": [f"run:{run_id}"], "feasible": True,
        }
    def optimizer_task(observations, _state):
        assert all("optimizer_objective" in row["metrics"] for row in observations)
        return TaskSpec(task_id="optimizer", project_id="project", design_id="gcd",
                        plugin_id="orfs-agent", inputs={"mode": "native_agent"},
                        timeout_seconds=60, labels={}, expected_artifacts=("optimizer_candidates",))
    def candidates(_run_id):
        return [{"candidate_id": "published-gp-ei-1", "platform_parameters": {
            "core_utilization_pct": 50, "place_density_lb_addon": .25,
            "tns_end_percent": 90, "global_placement_padding": 1,
            "detail_placement_padding": 1, "enable_dpo": 1,
            "cts_cluster_size": 20, "cts_cluster_diameter": 90,
        }}]
    service = ExternalOptimizerLoopService(
        checkpoints=PipelineCheckpointStore(tmp_path / "checkpoints.db"), runtime=runtime,
        runtime_store=store, observation_for_run=observation,
        optimizer_task=optimizer_task, candidates_for_run=candidates,
    )
    initial = {
        "status": "baseline_running", "design_id": "gcd", "platform": "nangate45",
        "objective_profile": "balanced", "optimizer_plugin": "orfs-agent@2025.1",
        "base_task": _base_task().to_dict(), "baseline_parameters": _base_task().parameters["flow_parameters"],
        "baseline_run_ids": [], "replica_or_seeds": [1, 2], "max_candidates": 2,
        "candidates_per_round": 1, "minimum_relative_improvement": .005,
        "frozen_constraints": ["clock_period_ns"], "round": 0, "candidate_count": 0,
        "stalled_rounds": 0, "history": [], "agent_events": [],
    }
    created = service.create(subject_id="gcd-demo", owner_id="alice", initial_state=initial)
    assert created["pipeline_kind"] == EXTERNAL_L2_KIND
    assert len(created["state"]["baseline_run_ids"]) == 2
    for run_id in created["state"]["baseline_run_ids"]:
        store.runs[run_id].status = _Status("succeeded")
    baseline_done = service.advance(created["pipeline_id"])
    assert baseline_done["state"]["status"] == "optimizer_pending"
    optimizer = service.advance(created["pipeline_id"])
    assert optimizer["state"]["status"] == "optimizer_running"
    store.runs[optimizer["state"]["optimizer_run_id"]].status = _Status("succeeded")
    candidates_submitted = service.advance(created["pipeline_id"])
    assert candidates_submitted["state"]["status"] == "candidate_running"
    candidate_runs = candidates_submitted["state"]["active_candidates"][0]["run_ids"]
    for run_id in candidate_runs:
        store.runs[run_id].status = _Status("succeeded")
    reviewed = service.advance(created["pipeline_id"])
    assert reviewed["state"]["candidate_count"] == 1
    assert reviewed["state"]["best_configuration"] == "published-gp-ei-1"
    assert reviewed["state"]["status"] == "optimizer_pending"


def test_admission_probes_supply_distinct_runtime_evidence_without_reusing_baseline_replicas(tmp_path: Path):
    store, runtime = _Store(), _Runtime(_Store())
    store = runtime.store

    def observation(run_id: str, _state):
        task = runtime.tasks[int(run_id.removeprefix("run-"))]
        parameters = dict(task.parameters["flow_parameters"])
        return {"observation_id": run_id, "run_id": run_id, "status": "succeeded",
                "parameters": parameters,
                "metrics": {"area_um2": 100.0, "power_W": 1.0,
                            "setup_wns_ns": .1, "drc_errors": 0.0},
                "artifact_refs": [f"run:{run_id}"], "feasible": True}

    service = ExternalOptimizerLoopService(
        checkpoints=PipelineCheckpointStore(tmp_path / "checkpoints.db"), runtime=runtime,
        runtime_store=store, observation_for_run=observation,
        optimizer_task=lambda observations, _state: TaskSpec(
            task_id="optimizer", project_id="project", design_id="gcd", plugin_id="orfs-agent",
            inputs={"observations": list(observations)}, timeout_seconds=60,
            labels={}, expected_artifacts=("optimizer_candidates",)),
        candidates_for_run=lambda _run_id: [],
    )
    base = _base_task()
    initial = {"status": "baseline_running", "design_id": "gcd", "platform": "nangate45",
               "objective_profile": "balanced", "optimizer_plugin": "orfs-agent@2025.1",
               "base_task": base.to_dict(), "baseline_parameters": base.parameters["flow_parameters"],
               "baseline_run_ids": [], "replica_or_seeds": [1, 2, 3], "max_candidates": 1,
               "candidates_per_round": 1, "minimum_relative_improvement": .005,
               "frozen_constraints": ["clock_period_ns"], "round": 0, "candidate_count": 0,
               "stalled_rounds": 0, "history": [], "agent_events": [],
               "admission_probe_recipes": [
                   {"recipe_id": "u45", "parameters": {"core_utilization_pct": 45}},
                   {"recipe_id": "u65", "parameters": {"core_utilization_pct": 65}},
               ]}
    checkpoint = service.create(subject_id="admission", owner_id=None, initial_state=initial)
    checkpoint = service.advance(checkpoint["pipeline_id"], execute=True, max_parallel=3)
    assert checkpoint["state"]["status"] == "admission_probe_running"
    checkpoint = service.advance(checkpoint["pipeline_id"], execute=True, max_parallel=2)
    assert checkpoint["state"]["status"] == "optimizer_pending"
    assert [row["parameters"]["core_utilization_pct"]
            for row in checkpoint["state"]["optimizer_observations"]] == [55, 45, 65]


def test_candidate_batch_validation_is_atomic_when_later_candidate_is_duplicate(tmp_path: Path):
    """A rejected batch must not leave an earlier queued Runtime prefix."""
    store, runtime = _Store(), _Runtime(_Store())
    store = runtime.store
    service = ExternalOptimizerLoopService(
        checkpoints=PipelineCheckpointStore(tmp_path / "checkpoints.db"), runtime=runtime,
        runtime_store=store, observation_for_run=lambda *_: {},
        optimizer_task=lambda *_: _base_task(), candidates_for_run=lambda *_: [],
    )
    initial = {
        "status": "optimizer_running", "design_id": "gcd", "platform": "nangate45",
        "objective_profile": "balanced", "optimizer_plugin": "orfs-agent@2025.1",
        "base_task": _base_task().to_dict(), "baseline_parameters": _base_task().parameters["flow_parameters"],
        "baseline_run_ids": [], "replica_or_seeds": [1], "max_candidates": 2,
        "candidates_per_round": 2, "minimum_relative_improvement": .005,
        "frozen_constraints": ["clock_period_ns"], "round": 0, "candidate_count": 0,
        "stalled_rounds": 0, "history": [], "agent_events": [], "warmup_runs": [],
    }
    checkpoint = service.create(subject_id="atomic-candidate-batch", owner_id=None, initial_state=initial)
    task_count_before = len(runtime.tasks)
    candidate = {"candidate_id": "gp-1", "platform_parameters": {
        "core_utilization_pct": 50, "place_density_lb_addon": .25,
    }}
    result = service._submit_candidates(checkpoint, [candidate, {**candidate, "candidate_id": "gp-2"}])
    assert result["state"]["status"] == "failed"
    assert len(runtime.tasks) == task_count_before


def test_paper_protocol_keeps_repeated_baseline_out_of_gp_training_and_confirms_winner(tmp_path: Path):
    """A performance campaign needs diverse warm-up data, not baseline copies."""
    store, runtime = _Store(), _Runtime(_Store())
    store = runtime.store
    optimizer_inputs: list[list[dict]] = []

    def observation(run_id: str, _state):
        task = runtime.tasks[int(run_id.removeprefix("run-"))]
        role = task.labels.get("external_l2_role")
        parameters = dict(task.parameters.get("flow_parameters") or {})
        # All non-baseline points are better in this isolated orchestration
        # test; the test concerns evidence routing, not a local optimizer.
        area = 100.0 if role == "baseline" else 90.0
        return {
            "observation_id": f"obs-{run_id}", "run_id": run_id, "status": "succeeded",
            "parameters": parameters,
            "metrics": {"area_um2": area, "power_W": 1.0,
                        "setup_wns_ns": .1, "drc_errors": 0.0},
            "artifact_refs": [f"run:{run_id}"], "feasible": True,
        }

    def optimizer_task(observations, _state):
        optimizer_inputs.append([dict(item) for item in observations])
        return TaskSpec(task_id="optimizer", project_id="project", design_id="gcd",
                        plugin_id="orfs-agent", inputs={"mode": "native_agent"},
                        timeout_seconds=60, labels={}, expected_artifacts=("optimizer_candidates",))

    def candidates(_run_id):
        return [{"candidate_id": f"gp-{index}", "platform_parameters": {
            "core_utilization_pct": 45 + index, "place_density_lb_addon": .20 + index * .01,
            "tns_end_percent": 90, "global_placement_padding": 1,
            "detail_placement_padding": 1, "enable_dpo": 1,
            "cts_cluster_size": 20, "cts_cluster_diameter": 90,
        }} for index in range(2)]

    service = ExternalOptimizerLoopService(
        checkpoints=PipelineCheckpointStore(tmp_path / "checkpoints.db"), runtime=runtime,
        runtime_store=store, observation_for_run=observation,
        optimizer_task=optimizer_task, candidates_for_run=candidates,
    )
    warmups = [{"recipe_id": f"warm-{index}", "parameters": {
        "core_utilization_pct": 30 + index, "place_density_lb_addon": .10 + index * .01,
        "tns_end_percent": 80 + index, "global_placement_padding": 1,
        "detail_placement_padding": 1, "enable_dpo": index % 2,
        "cts_cluster_size": 15 + index, "cts_cluster_diameter": 85 + index,
    }} for index in range(8)]
    initial = {
        "status": "baseline_running", "protocol_mode": "paper_comparable_external_l2_v1",
        "design_id": "gcd", "platform": "nangate45", "objective_profile": "balanced",
        "optimizer_plugin": "orfs-agent@2025.1", "base_task": _base_task().to_dict(),
        "baseline_parameters": _base_task().parameters["flow_parameters"], "baseline_run_ids": [],
        "replica_or_seeds": [1, 2, 3], "warmup_recipes": warmups, "warmup_runs": [],
        "warmup_seed": 4, "minimum_distinct_feasible_observations": 8,
        "confirmation_seeds": [5, 6, 7], "optimizer_seed": 11,
        "max_candidates": 2, "candidates_per_round": 2, "max_parallel": 2,
        "minimum_relative_improvement": .005, "frozen_constraints": ["clock_period_ns"],
        "round": 0, "candidate_count": 0, "stalled_rounds": 0, "history": [], "agent_events": [],
    }
    checkpoint = service.create(subject_id="paper-protocol", owner_id=None, initial_state=initial)
    # Baseline -> warmup -> upstream optimizer -> screening -> confirmation.
    checkpoint = service.advance(checkpoint["pipeline_id"], execute=True, max_parallel=3)
    assert checkpoint["state"]["status"] == "warmup_running"
    checkpoint = service.advance(checkpoint["pipeline_id"], execute=True, max_parallel=8)
    assert checkpoint["state"]["status"] == "optimizer_pending"
    assert len(checkpoint["state"]["optimizer_observations"]) == 9
    checkpoint = service.advance(checkpoint["pipeline_id"], execute=True, max_parallel=2)
    assert checkpoint["state"]["status"] == "optimizer_running"
    assert len(optimizer_inputs) == 1
    # The repeated baseline had three receipts but contributes one coordinate.
    assert len(optimizer_inputs[0]) == 9
    checkpoint = service.advance(checkpoint["pipeline_id"], execute=True, max_parallel=2)
    assert checkpoint["state"]["status"] == "candidate_running"
    checkpoint = service.advance(checkpoint["pipeline_id"], execute=True, max_parallel=2)
    assert checkpoint["state"]["status"] == "confirmation_running"
    checkpoint = service.advance(checkpoint["pipeline_id"], execute=True, max_parallel=3)
    assert checkpoint["state"]["status"] == "completed"
    assert checkpoint["state"]["final_confirmation"]["confirmed_improvement"] is True


def test_paper_protocol_rejects_baseline_replicas_disguised_as_warmup(tmp_path: Path):
    store, runtime = _Store(), _Runtime(_Store())
    store = runtime.store
    service = ExternalOptimizerLoopService(
        checkpoints=PipelineCheckpointStore(tmp_path / "checkpoints.db"), runtime=runtime,
        runtime_store=store, observation_for_run=lambda *_: {},
        optimizer_task=lambda *_: _base_task(), candidates_for_run=lambda *_: [],
    )
    repeated = {"core_utilization_pct": 55, "place_density_lb_addon": .2}
    initial = {
        "status": "baseline_running", "protocol_mode": "paper_comparable_external_l2_v1",
        "design_id": "gcd", "platform": "nangate45", "objective_profile": "balanced",
        "optimizer_plugin": "orfs-agent@2025.1", "base_task": _base_task().to_dict(),
        "baseline_parameters": repeated, "baseline_run_ids": [], "replica_or_seeds": [1, 2, 3],
        "warmup_recipes": [{"parameters": repeated} for _ in range(8)], "warmup_seed": 4,
        "minimum_distinct_feasible_observations": 8, "confirmation_seeds": [5, 6, 7],
        "optimizer_seed": 11, "max_candidates": 2, "candidates_per_round": 2,
        "minimum_relative_improvement": .005, "frozen_constraints": ["clock_period_ns"],
    }
    try:
        service.create(subject_id="bad-paper-protocol", owner_id=None, initial_state=initial)
    except ValueError as exc:
        assert "parameter-distinct" in str(exc)
    else:
        raise AssertionError("duplicate warm-up configurations must be rejected")


def test_target_calibrated_protocol_binds_the_admitted_domain_to_its_fingerprint(tmp_path: Path):
    store, runtime = _Store(), _Runtime(_Store())
    store = runtime.store
    service = ExternalOptimizerLoopService(
        checkpoints=PipelineCheckpointStore(tmp_path / "checkpoints.db"), runtime=runtime,
        runtime_store=store, observation_for_run=lambda *_: {},
        optimizer_task=lambda *_: _base_task(), candidates_for_run=lambda *_: [],
    )
    warmups = [{"recipe_id": f"warm-{index}", "parameters": {
        "core_utilization_pct": 30 + index, "place_density_lb_addon": .2,
        "tns_end_percent": 100, "global_placement_padding": 3,
        "detail_placement_padding": 3, "enable_dpo": 1,
        "cts_cluster_size": 20, "cts_cluster_diameter": 100,
    }} for index in range(8)]
    domain = {
        "source_domain_digest": "a" * 64,
        "search_parameter_names": ["core_utilization_pct"],
        "admissible_values": {"core_utilization_pct": list(range(30, 38))},
        "fixed_parameters": {
            "place_density_lb_addon": .2, "tns_end_percent": 100,
            "global_placement_padding": 3, "detail_placement_padding": 3,
            "enable_dpo": 1, "cts_cluster_size": 20, "cts_cluster_diameter": 100,
        },
    }
    initial = {
        "status": "baseline_running", "protocol_mode": "target_calibrated_external_l2_v2",
        "design_id": "aes", "platform": "sky130hd", "objective_profile": "balanced",
        "optimizer_plugin": "orfs-agent@2025.1", "base_task": _base_task().to_dict(),
        "baseline_parameters": _base_task().parameters["flow_parameters"], "baseline_run_ids": [],
        "replica_or_seeds": [1, 2, 3], "warmup_recipes": warmups, "warmup_runs": [],
        "warmup_seed": 4, "minimum_distinct_feasible_observations": 8,
        "confirmation_seeds": [5, 6, 7], "optimizer_seed": 11,
        "max_candidates": 2, "candidates_per_round": 2, "max_parallel": 2,
        "minimum_relative_improvement": .005, "frozen_constraints": ["clock_period_ns"],
        "admitted_target_domain": domain,
    }
    created = service.create(subject_id="target-domain", owner_id=None, initial_state=initial)
    assert created["state"]["admitted_target_domain"] == domain
    first_fingerprint = created["state"]["protocol_fingerprint"]
    changed = {**initial, "admitted_target_domain": {**domain, "source_domain_digest": "b" * 64}}
    try:
        service.create(subject_id="target-domain", owner_id=None, initial_state=changed)
    except ValueError as error:
        assert "different frozen" in str(error)
    else:
        raise AssertionError("a changed target domain must not reuse an existing campaign")
