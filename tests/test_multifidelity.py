from __future__ import annotations

import dataclasses
import platform
import sys
from pathlib import Path

import pytest

from openroad_platform_contracts import PluginManifest, TaskSpec
from openroad_platform_execution import PluginRegistry
from openroad_platform_scheduler import (
    FidelityPolicy, MultiFidelityScheduler, MultiFidelityStore, RuntimeStore,
    WorkflowRuntime, promotion_decision, proxy_calibration,
)


ADAPTER = Path(__file__).parent / "fixtures/echo_adapter.py"


def _runtime(tmp_path):
    plugin = PluginManifest(
        "echo", "1.0.0", (sys.executable, str(ADAPTER)), ("test.echo",),
        (platform.machine(),), {}, {},
        artifact_rules=({"kind": "report", "required": True},),
    )
    return WorkflowRuntime(
        RuntimeStore(tmp_path / "runtime.db"), PluginRegistry([plugin]),
        workspace_root=tmp_path / "runs",
    )


def _candidate(index):
    task = TaskSpec(
        f"base-{index}", "p", "d", plugin_id="echo",
        inputs={"message": str(index)},
        parameters={"flow_parameters": {"util": 30 + index}},
    )
    return {"candidate_id": f"candidate-{index}", "task": task,
            "effective_configuration_id": f"effective-{index}",
            "proposal_acquisition": float(index)}


def test_proxy_must_be_calibrated_before_it_can_prune():
    policy = FidelityPolicy(minimum_calibration_pairs=3, minimum_full_evaluations=1)
    missing = proxy_calibration([(1, 1), (2, 2)], minimum_pairs=3)
    decision = promotion_decision([
        {"candidate_id": "a", "quick_succeeded": True},
        {"candidate_id": "b", "quick_succeeded": True},
    ], policy, missing)
    assert set(decision["promoted_ids"]) == {"a", "b"}
    assert decision["mode"] == "calibration_full_replay"
    calibrated = proxy_calibration([(1, 1), (2, 2), (3, 3)], minimum_pairs=3)
    assert calibrated["eligible"] is True and calibrated["spearman"] == pytest.approx(1)
    ranked = promotion_decision([
        {"candidate_id": "a", "quick_succeeded": True, "quick_proxy_score": .1},
        {"candidate_id": "b", "quick_succeeded": True, "quick_proxy_score": .9},
        {"candidate_id": "c", "quick_succeeded": True, "quick_proxy_score": .2},
    ], FidelityPolicy(minimum_calibration_pairs=3, minimum_full_evaluations=1,
                      promotion_fraction=.3), calibrated)
    assert ranked["promoted_ids"] == ["b"]
    assert ranked["quick_metrics_are_final"] is False


def test_multifidelity_campaign_is_resumable_deduplicated_and_full_replayed(tmp_path):
    runtime = _runtime(tmp_path)
    store = MultiFidelityStore(tmp_path / "multifidelity.db")
    policy = FidelityPolicy(quick_stage="cts", full_stage="finish",
                            minimum_calibration_pairs=3, max_parallel=2)
    campaign = store.create(policy, [_candidate(1), _candidate(2)], campaign_id="mf-1")
    scheduler = MultiFidelityScheduler(store, runtime)
    first_ids = scheduler.ensure_quick_runs(campaign)
    assert scheduler.ensure_quick_runs(campaign) == first_ids
    result = scheduler.run_to_terminal(campaign, timeout_seconds=30)
    assert result["state"] == "completed"
    assert len(result["quick_run_ids"]) == 2
    assert len(result["full_run_ids"]) == 2
    assert result["promotion"]["quick_metrics_are_final"] is False
    assert all(item["decision"]["promoted"] for item in result["candidates"])


def test_multifidelity_store_rejects_duplicate_effective_configuration(tmp_path):
    store = MultiFidelityStore(tmp_path / "multifidelity.db")
    rows = [_candidate(1), {**_candidate(2), "effective_configuration_id": "effective-1"}]
    with pytest.raises(ValueError, match="Duplicate effective"):
        store.create(FidelityPolicy(), rows)


def test_logical_candidate_keeps_replicas_out_of_configuration_coverage(tmp_path):
    runtime = _runtime(tmp_path)
    store = MultiFidelityStore(tmp_path / "multifidelity.db")
    policy = FidelityPolicy(
        quick_stage="cts", full_stage="finish", quick_repetitions=1,
        full_repetitions=3, minimum_calibration_pairs=3, max_parallel=3,
    )
    candidate = {**_candidate(1), "replica_or_seeds": (101, 211, 307)}
    campaign = store.create(policy, [candidate], campaign_id="mf-replicated")
    scheduler = MultiFidelityScheduler(store, runtime)
    assert len(scheduler.ensure_quick_runs(campaign)) == 1
    result = scheduler.run_to_terminal(campaign, timeout_seconds=30)
    row = result["candidates"][0]
    assert len(row["quick_run_ids"]) == 1
    assert len(row["full_run_ids"]) == 3
    assert {item["effective_configuration_id"] for item in result["candidates"]} == {
        "effective-1"
    }
    assert {runtime.store.get_run(run_id).task_spec.parameters["or_seed"]
            for run_id in row["full_run_ids"]} == {101, 211, 307}
    # Restarting the scheduler reuses every durable task/run identity.
    restarted = MultiFidelityScheduler(
        MultiFidelityStore(tmp_path / "multifidelity.db"), runtime)
    resumed = restarted.run_to_terminal(campaign, timeout_seconds=30)
    assert resumed["quick_run_ids"] == result["quick_run_ids"]
    assert resumed["full_run_ids"] == result["full_run_ids"]


def test_quick_copy_drops_finish_artifacts_and_full_copy_restores_them(tmp_path):
    runtime = _runtime(tmp_path)
    store = MultiFidelityStore(tmp_path / "multifidelity.db")
    candidate = _candidate(1)
    candidate["task"] = dataclasses.replace(
        candidate["task"], expected_artifacts=("report", "def", "netlist", "gds"))
    campaign = store.create(
        FidelityPolicy(minimum_calibration_pairs=3), [candidate], campaign_id="mf-artifacts")
    scheduler = MultiFidelityScheduler(store, runtime)
    quick_id = scheduler.ensure_quick_runs(campaign)[0]
    assert runtime.store.get_run(quick_id).task_spec.expected_artifacts == ("report",)
    scheduler.run_bound((quick_id,), max_parallel=1)
    decision = scheduler.promote(campaign)
    assert decision["promoted_ids"] == ["candidate-1"]
    full_id = scheduler.ensure_full_runs(campaign)[0]
    assert set(runtime.store.get_run(full_id).task_spec.expected_artifacts) == {
        "report", "def", "netlist", "gds",
    }


def test_no_multifidelity_ablation_submits_zero_quick_and_full_replays_all(tmp_path):
    runtime = _runtime(tmp_path)
    store = MultiFidelityStore(tmp_path / "multifidelity.db")
    candidates = [
        {**_candidate(index), "replica_or_seeds": (101, 211, 307)}
        for index in (1, 2)
    ]
    campaign = store.create(FidelityPolicy(
        minimum_calibration_pairs=3, full_repetitions=3,
        skip_quick=True, max_parallel=3,
    ), candidates, campaign_id="mf-disabled")
    scheduler = MultiFidelityScheduler(store, runtime)
    result = scheduler.run_to_terminal(campaign, timeout_seconds=30)
    assert result["quick_run_ids"] == ()
    assert len(result["full_run_ids"]) == 6
    assert result["promotion"]["mode"] == "calibration_full_replay"
    assert result["promotion"]["calibration"]["reason"] == (
        "quick fidelity disabled by preregistered ablation")
    assert all(not row["quick_run_ids"] and len(row["full_run_ids"]) == 3
               for row in result["candidates"])
