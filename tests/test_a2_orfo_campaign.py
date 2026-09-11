from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from openroad_platform_execution import A2ORFODomain, ORFSAgentFullDomain
from openroad_platform_scheduler import (
    A2_ORFO_CAMPAIGN_KIND, A2ORFOCampaignService, PipelineCheckpointStore,
)


ROOT = Path(__file__).resolve().parents[1]
A2_SOURCE = ROOT / "var/external-sources/a2-orfo-8b20a3c-clean"
ORFS_SOURCE = ROOT / "var/external-sources/orfs-agent-730f1fa-clean-20260901"
PARAMETERS = {
    "UTIL", "GP_PAD", "DP_PAD", "HIER_SYNTH", "PIN_ADJ", "UP_ADJ",
    "TNS_End_Percent", "LB_ADDON", "CTS_CSIZE", "CTS_CDIA", "DPO", "CLK",
}


def _a2_protocol():
    return {
        "protocol_id": "a2-controller-test-v1",
        "a2_orfo_commit": "8b20a3c1f22934a39c7ba51ed0ec6dffe730da2d",
        "orfs_executor_commit": "730f1fa11f9c17c0aaac332412af2b2538f42e9b",
        "design": "aes", "platform": "sky130hd",
        "objective_set": ["ECP", "DWL", "COMBO"],
        "seed_policy": "test-seeds-v1",
        "budget": {"minimum_successful_observations": 4, "feedback_steps": 1},
        "evaluator": "protected-orfs-agent-full-v1",
        "objective_baselines": {"ecp": 4.721, "dwl": 589825.0},
        "design_bundle_sha256": "1" * 64,
        "pdk_bundle_sha256": "2" * 64,
        "toolchain_receipt_sha256": "3" * 64,
    }


def _execution_protocol():
    return {
        "protocol_id": "a2-controller-execution-test-v1",
        "orfs_agent_commit": "730f1fa11f9c17c0aaac332412af2b2538f42e9b",
        "orfs_commit": "ce8d36a7fef0ab9c47d183bcf078bce0f60f5a54",
        "design": "aes", "platform": "sky130hd",
        "objective_set": ["ECP", "DWL", "COMBO"],
        "seed_policy": "test-or-seeds-v1",
        "budget": {"initial_samples": 4, "rounds": 1,
                   "suggestions_per_round": 2, "confirmations": 1},
        "evaluator": "protected-orfs-agent-full-v1",
        "initialization_method": "upstream:A2-ORFO.OptimizationWorkflow.run_iteration",
        "design_bundle_sha256": "1" * 64,
        "pdk_bundle_sha256": "2" * 64,
        "toolchain_receipt_sha256": "3" * 64,
    }


def _domains():
    return (
        A2ORFODomain.from_upstream(
            source_root=A2_SOURCE, design="aes", platform_name="sky130hd",
            experiment_protocol=_a2_protocol()),
        ORFSAgentFullDomain.from_upstream(
            source_root=ORFS_SOURCE, design="aes", platform="sky130hd",
            experiment_protocol=_execution_protocol()),
    )


def _candidate(index):
    return {
        "UTIL": 25 + index, "GP_PAD": index % 4, "DP_PAD": (index + 1) % 4,
        "HIER_SYNTH": index % 2, "PIN_ADJ": .2 + index * .01,
        "UP_ADJ": .3 + index * .01, "TNS_End_Percent": 50 + index,
        "LB_ADDON": .2 + index * .01, "CTS_CSIZE": 10 + index,
        "CTS_CDIA": 80 + index, "DPO": index % 2, "CLK": 5.0 + index * .1,
    }


def _observations(domain):
    return [{
        "run_id": f"historical-{i}", "observation_id": f"historical-{i}",
        "status": "succeeded", "feasible": True,
        "protocol_sha256": domain.protocol_sha256,
        "candidate": _candidate(i), "metrics": {"ECP_final": 5.0 + i},
        "artifact_refs": [f"artifact:historical-{i}"],
    } for i in range(4)]


@dataclass
class _Status:
    value: str


@dataclass
class _Run:
    run_id: str
    status: _Status


class _Registry:
    def resolve(self, plugin_id, *, capability, **_kwargs):
        assert (plugin_id, capability) in {
            ("a2-orfo", "optimizer.l2.a2-orfo-initialize"),
            ("a2-orfo", "optimizer.l2.a2-orfo-policy"),
            ("a2-orfo", "optimizer.l2.a2-orfo-feedback"),
            ("orfs-agent", "optimizer.l2.upstream-full-candidate"),
        }
        return object()


class _Runtime:
    def __init__(self):
        self.registry = _Registry(); self.tasks = []; self.by_task = {}; self.runs = {}

    def submit_idempotent(self, task, *, capability):
        if task.task_id in self.by_task:
            prior = self.by_task[task.task_id]
            assert prior["task"].to_dict() == task.to_dict()
            return prior["run"]
        run = _Run(f"run-{len(self.tasks)}", _Status("queued"))
        self.tasks.append(task); self.runs[run.run_id] = run
        self.by_task[task.task_id] = {"task": task, "run": run, "capability": capability}
        return run

    def execute_once(self, run_id):
        task = self.tasks[int(run_id.removeprefix("run-"))]
        failed = task.inputs.get("mode") == "upstream_full_candidate" and \
            "-a2-step-" in task.task_id and \
            task.task_id.endswith("candidate-1")
        self.runs[run_id].status = _Status("failed" if failed else "succeeded")
        return self.runs[run_id]

    def get_run(self, run_id):
        return self.runs[run_id]


def _authorized(store):
    return store.create_or_get(
        pipeline_kind=A2_ORFO_CAMPAIGN_KIND, subject_id="l2-auth-a2", owner_id=None,
        initial_state={
            "status": "authorized",
            "request": {"plugin_id": "a2-orfo",
                        "capability": "optimizer.l2.a2-orfo-feedback",
                        "budget": {"max_eda_runs": 3, "max_parallel": 2}},
            "authorization": {"authorization_id": "l2-auth-a2"},
            "goal": {"project_id": "paper", "design_id": "aes"},
        })


def _checkpoint(index):
    unsigned = {"schema_version": 1, "optimized_prompts": {"step": index}}
    return {**unsigned, "sha256": hashlib.sha256(json.dumps(
        unsigned, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}


def test_durable_a2_policy_execution_feedback_and_restart(tmp_path):
    a2, execution = _domains()
    store = PipelineCheckpointStore(tmp_path / "campaign.sqlite")
    runtime = _Runtime()

    def policy_result(run_id):
        task = runtime.tasks[int(run_id.removeprefix("run-"))]
        step = int(task.task_id.rsplit("-", 1)[1])
        return {"candidates": [_candidate(4 + step * 2), _candidate(5 + step * 2)],
                "checkpoint": _checkpoint(step),
                "evidence_ref": f"runtime-artifact:policy-{run_id}"}

    def observation(run_id, _state):
        task = runtime.tasks[int(run_id.removeprefix("run-"))]
        failed = runtime.runs[run_id].status.value == "failed"
        return {
            "run_id": run_id, "observation_id": f"observation-{run_id}",
            "status": runtime.runs[run_id].status.value,
            "feasible": not failed,
            "protocol_sha256": execution.protocol_sha256,
            "candidate": dict(task.inputs["candidate"]),
            "metrics": {} if failed else {"ECP_final": task.inputs["candidate"]["CLK"]},
            "artifact_refs": [f"runtime-artifact:{run_id}"],
            **({"failure_category": "eda_failure"} if failed else {}),
        }

    service = A2ORFOCampaignService(
        checkpoints=store, runtime=runtime, runtime_store=runtime,
        observation_for_run=observation, policy_result_for_run=policy_result)
    configured = service.configure(
        _authorized(store)["pipeline_id"], a2_domain=a2,
        execution_domain=execution, objective="ECP",
        initial_observations=_observations(a2), optimizer_seeds=(41, 43),
        or_seed=701, n_suggestions=2, confirmation_seeds=(907,))
    assert configured["state"]["required_eda_runs"] == 3
    assert set(configured["state"]["a2_domain"]["parameter_names"]) == PARAMETERS

    # Replace the service halfway through: persisted state and idempotent task
    # IDs must resume without duplicate submissions.
    for _ in range(3):
        configured = service.advance(configured["pipeline_id"], execute=True,
                                     max_parallel=2)
    count_before_restart = len(runtime.tasks)
    service = A2ORFOCampaignService(
        checkpoints=PipelineCheckpointStore(tmp_path / "campaign.sqlite"),
        runtime=runtime, runtime_store=runtime,
        observation_for_run=observation, policy_result_for_run=policy_result)
    for _ in range(20):
        configured = service.advance(configured["pipeline_id"], execute=True,
                                     max_parallel=2)
        if configured["state"]["status"] in {
                "completed", "failed", "diagnosis_required"}:
            break
    assert configured["state"]["status"] == "completed"
    assert len(runtime.tasks) >= count_before_restart
    assert len({task.task_id for task in runtime.tasks}) == len(runtime.tasks)
    assert [entry["capability"] for entry in runtime.by_task.values()
            if entry["task"].plugin_id == "a2-orfo"] == [
                "optimizer.l2.a2-orfo-policy",
                "optimizer.l2.a2-orfo-feedback"]
    candidates = [task for task in runtime.tasks if task.plugin_id == "orfs-agent"]
    assert len(candidates) == 3
    assert all(set(task.inputs["candidate"]) == PARAMETERS for task in candidates)
    assert all(task.labels["optimizer_origin"].startswith("external:A2-ORFO@")
               for task in candidates)
    assert len(configured["state"]["measured_observations"]) == 2
    assert any(row["status"] == "failed"
               for row in configured["state"]["measured_observations"])
    assert len(configured["state"]["final_next_candidates"]) == 2
    assert len(configured["state"]["confirmation_observations"]) == 1


def test_a2_controller_rejects_shrunken_budget_and_configuration_drift(tmp_path):
    a2, execution = _domains()
    store = PipelineCheckpointStore(tmp_path / "campaign.sqlite")
    runtime = _Runtime()
    service = A2ORFOCampaignService(
        checkpoints=store, runtime=runtime, runtime_store=runtime,
        observation_for_run=lambda *_: {}, policy_result_for_run=lambda *_: {})
    checkpoint = _authorized(store)
    first = service.configure(
        checkpoint["pipeline_id"], a2_domain=a2, execution_domain=execution,
        objective="ECP", initial_observations=_observations(a2),
        optimizer_seeds=(41, 43), or_seed=701, n_suggestions=2,
        confirmation_seeds=(907,))
    assert service.configure(
        checkpoint["pipeline_id"], a2_domain=a2, execution_domain=execution,
        objective="ECP", initial_observations=_observations(a2),
        optimizer_seeds=(41, 43), or_seed=701, n_suggestions=2,
        confirmation_seeds=(907,))["revision"] == first["revision"]
    with pytest.raises(ValueError, match="configured differently"):
        service.configure(
            checkpoint["pipeline_id"], a2_domain=a2, execution_domain=execution,
            objective="ECP", initial_observations=_observations(a2),
            optimizer_seeds=(41, 43), or_seed=702, n_suggestions=2,
            confirmation_seeds=(907,))


def test_new_campaign_bootstraps_with_native_a2_initializer_then_measures(tmp_path):
    a2, execution = _domains()
    store = PipelineCheckpointStore(tmp_path / "bootstrap.sqlite")
    runtime = _Runtime()
    authorized = store.create_or_get(
        pipeline_kind=A2_ORFO_CAMPAIGN_KIND, subject_id="bootstrap", owner_id=None,
        initial_state={
            "status": "authorized",
            "request": {"plugin_id": "a2-orfo",
                        "capability": "optimizer.l2.a2-orfo-feedback",
                        "budget": {"max_eda_runs": 5, "max_parallel": 4}},
            "authorization": {"authorization_id": "bootstrap"},
            "goal": {"project_id": "paper", "design_id": "aes"}})

    def policy_result(run_id):
        task = runtime.tasks[int(run_id.removeprefix("run-"))]
        candidates = ([_candidate(index) for index in range(4)]
                      if task.inputs["mode"] == "native_initialize"
                      else [_candidate(8)])
        return {"candidates": candidates, "checkpoint": _checkpoint(0),
                "evidence_ref": f"runtime-artifact:policy-{run_id}"}

    def observation(run_id, _state):
        task = runtime.tasks[int(run_id.removeprefix("run-"))]
        return {"run_id": run_id, "observation_id": f"observation-{run_id}",
                "status": "succeeded", "feasible": True,
                "protocol_sha256": execution.protocol_sha256,
                "candidate": dict(task.inputs["candidate"]),
                "metrics": {"ECP_final": float(task.inputs["candidate"]["CLK"])},
                "artifact_refs": [f"runtime-artifact:{run_id}"]}

    service = A2ORFOCampaignService(
        checkpoints=store, runtime=runtime, runtime_store=runtime,
        observation_for_run=observation, policy_result_for_run=policy_result)
    checkpoint = service.configure(
        authorized["pipeline_id"], a2_domain=a2, execution_domain=execution,
        objective="ECP", initial_observations=(), optimizer_seeds=(37, 41),
        or_seed=701, n_suggestions=1)
    assert checkpoint["state"]["status"] == "bootstrap_pending"
    assert checkpoint["state"]["bootstrap_count"] == 4
    assert checkpoint["state"]["required_eda_runs"] == 5
    for _ in range(30):
        checkpoint = service.advance(
            checkpoint["pipeline_id"], execute=True, max_parallel=4)
        if checkpoint["state"]["status"] in {
                "completed", "failed", "diagnosis_required"}:
            break
    assert checkpoint["state"]["status"] == "completed"
    assert len(checkpoint["state"]["bootstrap_observations"]) == 4
    assert len(checkpoint["state"]["measured_observations"]) == 5
    modes = [task.inputs["mode"] for task in runtime.tasks]
    assert modes.count("native_initialize") == 1
    assert modes.count("native_policy") == 2
    assert modes.count("upstream_full_candidate") == 5

    underfunded = store.create_or_get(
        pipeline_kind=A2_ORFO_CAMPAIGN_KIND, subject_id="underfunded", owner_id=None,
        initial_state={"status": "authorized",
                       "request": {"plugin_id": "a2-orfo",
                                   "capability": "optimizer.l2.a2-orfo-feedback",
                                   "budget": {"max_eda_runs": 2, "max_parallel": 2}},
                       "goal": {"project_id": "paper", "design_id": "aes"}})
    with pytest.raises(ValueError, match="below A2 campaign"):
        service.configure(
            underfunded["pipeline_id"], a2_domain=a2, execution_domain=execution,
            objective="ECP", initial_observations=_observations(a2),
            optimizer_seeds=(41, 43), or_seed=701, n_suggestions=2,
            confirmation_seeds=(907,))


def test_product_campaign_shape_preserves_26_plus_five_by_25(tmp_path):
    _, execution = _domains()
    protocol = _a2_protocol()
    protocol["budget"]["feedback_steps"] = 5
    a2 = A2ORFODomain.from_upstream(
        source_root=A2_SOURCE, design="aes", platform_name="sky130hd",
        experiment_protocol=protocol)
    store = PipelineCheckpointStore(tmp_path / "product.sqlite")
    runtime = _Runtime()
    authorized = store.create_or_get(
        pipeline_kind=A2_ORFO_CAMPAIGN_KIND, subject_id="product-151",
        owner_id=None, initial_state={
            "status": "authorized",
            "request": {"plugin_id": "a2-orfo",
                        "capability": "optimizer.l2.a2-orfo-feedback",
                        "budget": {"max_eda_runs": 151, "max_parallel": 4}},
            "authorization": {"authorization_id": "product-151"},
            "goal": {"project_id": "paper", "design_id": "aes"},
        })
    configured = A2ORFOCampaignService(
        checkpoints=store, runtime=runtime, runtime_store=runtime,
        observation_for_run=lambda *_: {}, policy_result_for_run=lambda *_: {},
    ).configure(
        authorized["pipeline_id"], a2_domain=a2,
        execution_domain=execution, objective="ECP", initial_observations=(),
        optimizer_seeds=(401, 403, 405, 407, 409, 411), or_seed=401,
        n_suggestions=25, confirmation_seeds=(), bootstrap_samples=26,
    )
    state = configured["state"]
    assert state["bootstrap_count"] == 26
    assert state["n_suggestions"] == 25
    assert state["required_eda_runs"] == 151
    assert runtime.tasks == []
