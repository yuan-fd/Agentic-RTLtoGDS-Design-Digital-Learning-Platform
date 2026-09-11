from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from openroad_platform_execution import ORFSAgentFullDomain
from openroad_platform_scheduler import (
    ORFS_AGENT_FULL_CAMPAIGN_KIND,
    ORFSAgentFullCampaignService,
    PipelineCheckpointStore,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "var/external-sources/orfs-agent-730f1fa-clean-20260901"
PARAMETERS = (
    "CLK", "UTIL", "TNS_End_Percent", "GP_PAD", "DP_PAD", "DPO",
    "PIN_ADJ", "UP_ADJ", "LB_ADDON", "HIER_SYNTH", "CTS_CSIZE", "CTS_CDIA",
)


def _protocol() -> dict:
    return {
        "protocol_id": "orfs-agent-upstream-full-test-v1",
        "orfs_agent_commit": "730f1fa11f9c17c0aaac332412af2b2538f42e9b",
        "orfs_commit": "ce8d36a7fef0ab9c47d183bcf078bce0f60f5a54",
        "design": "aes", "platform": "sky130hd",
        "objective_set": ["ECP", "DWL", "COMBO"],
        "seed_policy": "frozen-test-seeds-v1",
        "budget": {"initial_samples": 2, "rounds": 2,
                   "suggestions_per_round": 2, "confirmations": 2},
        "evaluator": "protected-orfs-agent-full-v1",
        "initialization_method": "upstream:OptimizationWorkflow.generate_initial_parameters",
        "design_bundle_sha256": "1" * 64, "pdk_bundle_sha256": "2" * 64,
        "toolchain_receipt_sha256": "3" * 64,
    }


def _domain() -> ORFSAgentFullDomain:
    return ORFSAgentFullDomain.from_upstream(
        source_root=SOURCE, design="aes", platform="sky130hd",
        experiment_protocol=_protocol(),
    )


def _candidate(index: int) -> dict[str, int | float]:
    return {
        "CLK": 4.5 + index * .05, "UTIL": 20 + index,
        "TNS_End_Percent": 100 - index, "GP_PAD": index % 4,
        "DP_PAD": (index + 1) % 4, "DPO": index % 2,
        "PIN_ADJ": .3, "UP_ADJ": .4, "LB_ADDON": .2 + index * .01,
        "HIER_SYNTH": index % 2, "CTS_CSIZE": 10 + index,
        "CTS_CDIA": 80 + index,
    }


@dataclass
class _Status:
    value: str


@dataclass
class _Run:
    run_id: str
    status: _Status


class _Registry:
    def resolve(self, plugin_id, *, capability, **_kwargs):
        assert plugin_id == "orfs-agent"
        if capability not in {
            "optimizer.l2.upstream-full-12d",
            "optimizer.l2.upstream-full-candidate",
        }:
            raise LookupError(capability)
        return object()


class _Runtime:
    def __init__(self):
        self.registry = _Registry()
        self.runs: dict[str, _Run] = {}
        self.tasks = []
        self.by_task_id = {}

    def submit_idempotent(self, task, *, capability):
        expected = ("optimizer.l2.upstream-full-candidate"
                    if task.inputs["mode"] == "upstream_full_candidate"
                    else "optimizer.l2.upstream-full-12d")
        assert capability == expected
        if task.task_id in self.by_task_id:
            prior = self.by_task_id[task.task_id]
            assert prior["task"].to_dict() == task.to_dict()
            return prior["run"]
        run = _Run(f"run-{len(self.tasks)}", _Status("queued"))
        self.tasks.append(task); self.runs[run.run_id] = run
        self.by_task_id[task.task_id] = {"task": task, "run": run}
        return run

    def execute_once(self, run_id):
        task = self.tasks[int(run_id.removeprefix("run-"))]
        failed = "round-0-candidate-1" in task.task_id
        self.runs[run_id].status = _Status("failed" if failed else "succeeded")
        return self.runs[run_id]

    def get_run(self, run_id):
        return self.runs[run_id]


def _authorized(checkpoints: PipelineCheckpointStore) -> dict:
    return checkpoints.create_or_get(
        pipeline_kind=ORFS_AGENT_FULL_CAMPAIGN_KIND, subject_id="l2-auth-test",
        owner_id=None, initial_state={
            "status": "authorized",
            "request": {"plugin_id": "orfs-agent",
                        "capability": "optimizer.l2.upstream-full-12d",
                        "budget": {"max_eda_runs": 8, "max_parallel": 4}},
            "authorization": {"authorization_id": "l2-auth-test"},
            "goal": {"project_id": "paper", "design_id": "aes"},
        },
    )


def test_full_campaign_runs_upstream_tasks_and_feedback_with_failures_preserved(tmp_path):
    checkpoints = PipelineCheckpointStore(tmp_path / "campaign.sqlite")
    runtime = _Runtime()

    def candidates(run_id):
        task = runtime.tasks[int(run_id.removeprefix("run-"))]
        if task.inputs["mode"] == "upstream_full_initialize":
            return [_candidate(0), _candidate(1)]
        assert task.inputs["mode"] == "upstream_full_policy"
        round_index = int(task.task_id.rsplit("-", 1)[1])
        return [_candidate(2 + round_index * 2), _candidate(3 + round_index * 2)]

    def observation(run_id, _state):
        task = runtime.tasks[int(run_id.removeprefix("run-"))]
        run = runtime.runs[run_id]
        candidate = dict(task.inputs["candidate"])
        failed = run.status.value != "succeeded"
        return {
            "run_id": run_id, "observation_id": f"obs-{run_id}",
            "status": run.status.value, "feasible": not failed,
            "protocol_sha256": task.inputs["parameter_domain"]["protocol_sha256"],
            "candidate": candidate,
            "metrics": {} if failed else {
                "finish__timing__setup__ws": .1,
                "detailedroute__route__wirelength": 600000.0 + candidate["UTIL"],
                "ECP_final": candidate["CLK"] - .1,
            },
            "artifact_refs": [f"runtime:{run_id}:raw-failure" if failed
                              else f"runtime:{run_id}:protected-evaluation"],
        }

    service = ORFSAgentFullCampaignService(
        checkpoints=checkpoints, runtime=runtime, runtime_store=runtime,
        observation_for_run=observation, candidates_for_run=candidates,
    )
    checkpoint = _authorized(checkpoints)
    configured = service.configure(
        checkpoint["pipeline_id"], domain=_domain(), objective="ECP",
        initialization_seed=23, screening_seed=101,
        confirmation_seeds=(503, 601),
    )
    assert configured["state"]["status"] == "initialization_pending"
    assert configured["state"]["required_eda_runs"] == 8

    # Each call advances one durable transition family; execution is always
    # delegated to Runtime and can therefore resume after any call boundary.
    for _ in range(20):
        configured = service.advance(
            checkpoint["pipeline_id"], execute=True, max_parallel=4)
        if configured["state"]["status"] in {"completed", "failed", "diagnosis_required"}:
            break
    assert configured["state"]["status"] == "completed"
    assert configured["state"]["completion_reason"] == (
        "full_budget_and_independent_confirmations_completed")

    modes = [task.inputs["mode"] for task in runtime.tasks]
    assert modes.count("upstream_full_initialize") == 1
    assert modes.count("upstream_full_policy") == 2
    assert modes.count("upstream_full_candidate") == 8
    candidate_tasks = [task for task in runtime.tasks
                       if task.inputs["mode"] == "upstream_full_candidate"]
    assert all(task.plugin_id == "orfs-agent" for task in candidate_tasks)
    assert all(tuple(task.inputs["candidate"]) == PARAMETERS for task in candidate_tasks)
    assert {task.parameters["or_seed"] for task in candidate_tasks[-2:]} == {503, 601}

    policy_tasks = [task for task in runtime.tasks
                    if task.inputs["mode"] == "upstream_full_policy"]
    assert len(policy_tasks[0].inputs["observations"]) == 2
    # One of round zero's two measurements fails.  It remains in audit state,
    # while only the successful row becomes GP/EI training feedback.
    assert len(policy_tasks[1].inputs["observations"]) == 3
    failed_rows = [row for row in configured["state"]["observations"]
                   if row["status"] == "failed"]
    assert len(failed_rows) == 1
    assert failed_rows[0]["artifact_refs"][0].endswith(":raw-failure")
    assert configured["state"]["history"][0]["optimizer_feedback_count"] == 1

    with pytest.raises(ValueError, match="exceeds the authorized"):
        service.advance(checkpoint["pipeline_id"], execute=True, max_parallel=5)


def test_full_campaign_configuration_is_idempotent_and_rejects_budget_or_drift(tmp_path):
    checkpoints = PipelineCheckpointStore(tmp_path / "campaign.sqlite")
    runtime = _Runtime()
    service = ORFSAgentFullCampaignService(
        checkpoints=checkpoints, runtime=runtime, runtime_store=runtime,
        observation_for_run=lambda *_: {}, candidates_for_run=lambda *_: [],
    )
    checkpoint = _authorized(checkpoints)
    first = service.configure(
        checkpoint["pipeline_id"], domain=_domain(), objective="ECP",
        initialization_seed=23, screening_seed=101, confirmation_seeds=(503, 601),
    )
    second = service.configure(
        checkpoint["pipeline_id"], domain=_domain(), objective="ECP",
        initialization_seed=23, screening_seed=101, confirmation_seeds=(503, 601),
    )
    assert second["revision"] == first["revision"]
    with pytest.raises(ValueError, match="configured differently"):
        service.configure(
            checkpoint["pipeline_id"], domain=_domain(), objective="ECP",
            initialization_seed=24, screening_seed=101,
            confirmation_seeds=(503, 601),
        )

    underfunded = checkpoints.create_or_get(
        pipeline_kind=ORFS_AGENT_FULL_CAMPAIGN_KIND, subject_id="underfunded",
        owner_id=None, initial_state={
            "status": "authorized",
            "request": {"plugin_id": "orfs-agent",
                        "capability": "optimizer.l2.upstream-full-12d",
                        "budget": {"max_eda_runs": 7, "max_parallel": 4}},
            "goal": {"project_id": "paper"},
        },
    )
    with pytest.raises(ValueError, match="below the frozen"):
        service.configure(
            underfunded["pipeline_id"], domain=_domain(), objective="ECP",
            initialization_seed=23, screening_seed=101,
            confirmation_seeds=(503, 601),
        )
