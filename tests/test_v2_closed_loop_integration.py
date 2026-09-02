from __future__ import annotations

import platform
import os
import sys
from pathlib import Path

import pytest

from apps.api.app import ApiState
from openroad_platform_contracts import PluginManifest
from openroad_platform_execution import PluginRegistry


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / "fixtures" / "closed_loop_orfs_adapter.py"


def _state(tmp_path: Path, monkeypatch) -> tuple[ApiState, dict]:
    state = ApiState(
        tmp_path / "platform.db", tmp_path / "uploads", tmp_path / "orfs",
        design_root=tmp_path / "designs", legacy_root=tmp_path / "legacy",
        runtime_db_path=tmp_path / "runtime.db",
        optimization_db_path=tmp_path / "optimization.db",
        load_taiwei_plugin=False,
    )

    def fake_synthesis(_rtl: Path, module: str, directory: Path) -> Path:
        netlist = directory / f"{module}.netlist.v"
        netlist.write_text(_rtl.read_text(encoding="utf-8"), encoding="utf-8")
        return netlist

    monkeypatch.setattr(state.designs, "_synthesize", fake_synthesis)
    design = state.designs.import_rtl(
        filename="closed_loop_top.v",
        source=("module closed_loop_top(input clk, input a, output reg y); "
                "always @(posedge clk) y <= a; endmodule\n"),
    )
    kinds = ("report", "odb", "config", "toolchain_snapshot", "parameter_contract", "run_result",
             "design_input_manifest",
             "def", "netlist", "gds")
    manifest = PluginManifest(
        plugin_id="orfs", plugin_version="1.1.0",
        adapter_entry=(sys.executable, str(FIXTURE)),
        capabilities=("eda.rtl_to_gds",), supported_arch=(platform.machine(),),
        input_schema={"type": "object"}, output_schema={"type": "object"},
        artifact_rules=tuple({"kind": kind, "required": kind != "report"}
                             for kind in kinds),
        environment=({"OPENROAD_TEST_FAIL_QUICK":
                      os.environ["OPENROAD_TEST_FAIL_QUICK"]}
                     if os.environ.get("OPENROAD_TEST_FAIL_QUICK") else {}),
        default_timeout_seconds=30,
    )
    state.runtime.registry = PluginRegistry([manifest])
    return state, design


def _payload(design_id: str) -> dict:
    return {
        "design_id": design_id, "experiment_key": "integration-resume",
        "objective_profile": "balanced", "repetitions": 3,
        "max_rounds": 7, "stall_window": 3,
        "minimum_relative_improvement": .25,
        "optimizer_seed": 20260824,
        "optimizer_minimum_initial": 4,
        "optimizer_backend": "sobol-scrambled-mixed-v1",
        "replica_or_seeds": [10101, 20202, 30303],
    }


def test_closed_loop_records_stall_diagnosis_but_runs_fixed_budget(tmp_path, monkeypatch):
    state, design = _state(tmp_path, monkeypatch)
    created = state.start_bayesian_closed_loop(_payload(design["id"]))
    assert created["execution_started"] is True
    assert len(created["state"]["active_run_ids"]) == 3

    result = state.run_bayesian_closed_loop_to_boundary(
        created["pipeline_id"], {"max_transitions": 16})
    loop = result["state"]
    assert loop["status"] in {"completed", "diagnosis_required"}
    assert loop["stall_diagnoses"]
    assert [item["kind"] for item in loop["history"]] == ["baseline"] + ["bo_candidate"] * 7
    assert all(item["summary"]["replicas"] == 3 for item in loop["history"])
    assert all(item["summary"]["failure_rate"] == 0 for item in loop["history"])
    assert all("iqr" in item["summary"]["metrics"]["area_um2"]
               for item in loop["history"])
    # 3 baseline full replicas + 7 quick CTS probes + 7 x 3 full replays.
    assert len(state.runtime_store.list_runs()) == 31
    assert len(state.optimization_store.observations(loop["study_id"])) == 24
    quick_runs = [run for run in state.runtime_store.list_runs()
                  if run.task_spec.labels.get("fidelity") == "quick"]
    assert len(quick_runs) == 7
    assert all(run.task_spec.parameters["target_stage"] == "cts" for run in quick_runs)
    assert all(item["quick_proxy"]["quick_metrics_are_final"] is False
               for item in loop["history"] if item["kind"] == "bo_candidate")
    assert state.optimization_store.get(loop["study_id"]).seed == 20260824
    for item in loop["history"]:
        seeds = [state.runtime_store.get_run(run_id).task_spec.parameters["or_seed"]
                 for run_id in item["summary"]["run_ids"]]
        assert seeds == [10101, 20202, 30303]
    phases = [item["phase"] for item in loop["agent_events"]]
    assert phases[:3] == ["map", "semantic", "experiment"]
    assert {"hypothesis", "implement", "validate", "review",
            "memory", "diagnosis"} <= set(phases)
    assert all(item.get("run_ids") for item in loop["agent_events"]
               if item["phase"] == "validate")
    assert all(item.get("run_ids") for item in loop["agent_events"]
               if item["phase"] == "memory" and "outcome" in item)
    causal = loop["stall_diagnoses"][-1]["packet"]["causal_hypothesis"]
    assert causal["status"] == "draft"
    assert causal["proposed_intervention"]["kind"] == "preregistered_2x2_interaction"
    assert causal["proposed_intervention"]["execution_allowed"] is False
    assert state.hypothesis_ledger.history(causal["hypothesis_id"])

    # A repeated HTTP-equivalent resume is a read, not another experiment.
    resumed = state.run_bayesian_closed_loop_to_boundary(
        created["pipeline_id"], {"max_transitions": 16})
    assert resumed["state"]["history"] == loop["history"]
    assert len(state.runtime_store.list_runs()) == 31


def test_closed_loop_freezes_spec_clock_outside_bo_space(tmp_path, monkeypatch):
    state, design = _state(tmp_path, monkeypatch)
    payload = _payload(design["id"])
    payload["parameter_space"] = {
        "core_utilization_pct": [20.0, 65.0],
        "place_density": [.35, .78],
        "clock_period_ns": [5.0, 20.0],
    }
    with pytest.raises(ValueError, match="unsupported.*clock_period_ns"):
        state.start_bayesian_closed_loop(payload)


def test_experiment_key_cannot_resume_a_different_optimizer_protocol(tmp_path, monkeypatch):
    state, design = _state(tmp_path, monkeypatch)
    payload = _payload(design["id"])
    state.start_bayesian_closed_loop(payload)
    changed = {**payload, "optimizer_seed": payload["optimizer_seed"] + 1}
    with pytest.raises(ValueError, match="different frozen DSE protocol"):
        state.start_bayesian_closed_loop(changed)


def test_all_infeasible_search_is_completed_nonattainment_not_excluded(tmp_path, monkeypatch):
    state, design = _state(tmp_path, monkeypatch)
    payload = _payload(design["id"])
    payload.update({
        "experiment_key": "all-infeasible",
        "max_rounds": 1,
        "hard_constraints": [
            {"metric": "drc_errors", "operator": "<=", "threshold": -1.0}],
    })
    created = state.start_bayesian_closed_loop(payload)
    result = state.run_bayesian_closed_loop_to_boundary(
        created["pipeline_id"], {"max_transitions": 8})["state"]

    assert result["status"] == "completed"
    assert result["study_outcome"] == \
        "fixed_budget_exhausted_no_feasible_configuration"
    assert result["best_feasible"] is False
    assert result["best_utility"] == -1.0
    assert result["history"][0]["utility"] is None
    assert result["diagnosis"]["reason"] == (
        "no hard-constraint-feasible baseline or candidate")


def test_stateful_l2_portfolio_records_auditable_strategy_metadata(tmp_path, monkeypatch):
    state, design = _state(tmp_path, monkeypatch)
    payload = _payload(design["id"])
    payload.update({
        "experiment_key": "stateful-l2", "optimizer_backend": "stateful-l2-portfolio-v1",
        "max_rounds": 1, "optimizer_minimum_initial": 4,
    })
    created = state.start_bayesian_closed_loop(payload)
    result = state.run_bayesian_closed_loop_to_boundary(
        created["pipeline_id"], {"max_transitions": 8})["state"]
    proposal = next(item for item in result["history"] if item["kind"] == "bo_candidate")
    strategy = proposal["model_metadata"]["state_tuning"]
    assert strategy["mode"] in {"feasibility_recovery", "global_exploration"}
    assert strategy["evidence_refs"]
    assert len(strategy["evidence_refs"]) <= 8
    assert any(ref.startswith("edair:") for ref in strategy["evidence_refs"])


def test_research_flow_timeout_is_bounded_and_frozen_in_every_replica(tmp_path, monkeypatch):
    state, design = _state(tmp_path, monkeypatch)
    payload = _payload(design["id"])
    payload.update({"stage_timeout_seconds": 7200, "flow_timeout_seconds": 14400})
    created = state.start_bayesian_closed_loop(payload)
    for run_id in created["state"]["active_run_ids"]:
        task = state.runtime_store.get_run(run_id).task_spec
        assert task.parameters["stage_timeout_seconds"] == 7200
        assert task.timeout_seconds == 14400
    payload["stage_timeout_seconds"] = 14_401
    payload["experiment_key"] = "invalid-timeout"
    with pytest.raises(ValueError, match="stage_timeout_seconds"):
        state.start_bayesian_closed_loop(payload)


def test_closed_loop_replica_submission_recovers_missing_suffix(tmp_path, monkeypatch):
    state, design = _state(tmp_path, monkeypatch)
    original_submit = state.runtime.submit
    calls = 0

    def interrupted_submit(task, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected process interruption")
        return original_submit(task, **kwargs)

    monkeypatch.setattr(state.runtime, "submit", interrupted_submit)
    with pytest.raises(RuntimeError, match="injected"):
        state.start_bayesian_closed_loop(_payload(design["id"]))
    checkpoint = state.pipeline_checkpoints.create_or_get(
        pipeline_kind="bo-gp-closed-loop-v2", subject_id="integration-resume",
        owner_id=None, initial_state={},
    )
    assert len(checkpoint["state"]["active_run_ids"]) == 1

    monkeypatch.setattr(state.runtime, "submit", original_submit)
    resumed = state.start_bayesian_closed_loop(_payload(design["id"]))
    ids = resumed["state"]["active_run_ids"]
    assert len(ids) == len(set(ids)) == 3
    assert len(state.runtime_store.list_runs()) == 3


def test_candidate_round_recovers_partial_replica_submission(tmp_path, monkeypatch):
    state, design = _state(tmp_path, monkeypatch)
    created = state.start_bayesian_closed_loop(_payload(design["id"]))
    original_submit = state.runtime.submit
    calls = 0

    def interrupted_submit(task, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("candidate submission interrupted")
        return original_submit(task, **kwargs)

    monkeypatch.setattr(state.runtime, "submit", interrupted_submit)
    with pytest.raises(RuntimeError, match="candidate submission"):
        state.run_bayesian_closed_loop_to_boundary(
            created["pipeline_id"], {"max_transitions": 2})
    interrupted = state.pipeline_checkpoints.get(created["pipeline_id"])["state"]
    assert interrupted["active_kind"] == "candidate_batch"
    assert interrupted["round"] == 7
    assert len(interrupted["active_proposals"]) == 7
    first_proposal_id = interrupted["active_proposals"][0]["proposal_id"]
    durable_rows = state.multifidelity_store.candidates(
        interrupted["active_multifidelity_campaign_id"])
    assert sum(len(item["quick_run_ids"]) for item in durable_rows) == 1

    monkeypatch.setattr(state.runtime, "submit", original_submit)
    finished = state.run_bayesian_closed_loop_to_boundary(
        created["pipeline_id"], {"max_transitions": 16})["state"]
    assert finished["status"] in {"completed", "diagnosis_required"}
    assert finished["stall_diagnoses"]
    first_round = [item for item in finished["history"] if item["round"] == 1][0]
    assert first_round["summary"]["replicas"] == 3
    round_runs = [state.runtime_store.get_run(run_id)
                  for run_id in first_round["summary"]["run_ids"]]
    assert len({run.run_id for run in round_runs}) == 3
    assert all(run.task_spec.labels["optimizer_proposal_id"]
               == first_proposal_id for run in round_runs)


def test_objective_profile_is_an_effective_ranking_policy(tmp_path, monkeypatch):
    state, _ = _state(tmp_path, monkeypatch)
    baseline = {
        "eligible": True, "complete_objectives": True, "successes": 3, "replicas": 3,
        "metrics": {
            "area_um2": {"median": 100.0},
            "setup_wns_ns": {"median": 1.0},
            "power_W": {"median": 1.0},
        },
    }
    smaller_but_slower = {
        **baseline, "metrics": {
            "area_um2": {"median": 80.0},
            "setup_wns_ns": {"median": .8},
            "power_W": {"median": 1.0},
        },
    }
    faster_but_larger = {
        **baseline, "metrics": {
            "area_um2": {"median": 120.0},
            "setup_wns_ns": {"median": 1.2},
            "power_W": {"median": 1.0},
        },
    }
    from openroad_platform_analysis import relative_utility
    assert relative_utility(smaller_but_slower, baseline, state._v2_objectives("area")) > 0
    assert relative_utility(faster_but_larger, baseline, state._v2_objectives("area")) < 0
    assert relative_utility(smaller_but_slower, baseline, state._v2_objectives("timing")) < 0
    assert relative_utility(faster_but_larger, baseline, state._v2_objectives("timing")) > 0


def test_second_study_warm_starts_from_verified_exact_context_memory(tmp_path, monkeypatch):
    state, design = _state(tmp_path, monkeypatch)
    first = state.start_bayesian_closed_loop(_payload(design["id"]))
    state.run_bayesian_closed_loop_to_boundary(
        first["pipeline_id"], {"max_transitions": 16})

    second_payload = {**_payload(design["id"]),
                      "experiment_key": "second-memory-study"}
    second = state.start_bayesian_closed_loop(second_payload)
    observed = state.run_bayesian_closed_loop_to_boundary(
        second["pipeline_id"], {"max_transitions": 1})["state"]
    assert len(observed["memory_prior_observations"]) == 24
    assert len(observed["memory_prior_refs"]) == 24
    assert observed["validated_knowledge_bundle"]["bundle_fingerprint"]
    proposal = state.optimization_store.proposals(observed["study_id"])[0]
    # Iteration counts only the new study's three baseline replicas; prior
    # evidence is cited and used by the GP without pretending it was rerun.
    assert proposal.iteration == 3
    prior_refs = {pointer.ref for pointer in proposal.evidence}
    assert any(ref.startswith("run:") for ref in prior_refs)


def test_no_memory_ablation_neither_reads_nor_writes_cross_study_memory(tmp_path, monkeypatch):
    state, design = _state(tmp_path, monkeypatch)
    first = state.start_bayesian_closed_loop(_payload(design["id"]))
    state.run_bayesian_closed_loop_to_boundary(
        first["pipeline_id"], {"max_transitions": 16})
    before = len(state.tenant_learning_store.list(
        "system-auto", "openroad-platform"))

    payload = {**_payload(design["id"]),
               "experiment_key": "no-memory-study", "max_rounds": 2,
               "ablation_id": "no_memory"}
    created = state.start_bayesian_closed_loop(payload)
    loop = state.run_bayesian_closed_loop_to_boundary(
        created["pipeline_id"], {"max_transitions": 8})["state"]
    assert loop["memory_prior_observations"] == []
    assert loop["memory_prior_refs"] == []
    assert loop["validated_knowledge_bundle"] is None
    assert loop["optimization_memory"] == {
        "disabled_by_ablation": True, "active_artifacts": []}
    assert len(state.tenant_learning_store.list(
        "system-auto", "openroad-platform")) == before
    assert any(event.get("memory_enabled") is False
               for event in loop["agent_events"] if event["phase"] == "memory")


def test_no_multifidelity_ablation_has_no_quick_runtime_runs(tmp_path, monkeypatch):
    state, design = _state(tmp_path, monkeypatch)
    payload = {**_payload(design["id"]),
               "experiment_key": "no-multifidelity-study", "max_rounds": 2,
               "ablation_id": "no_multifidelity"}
    created = state.start_bayesian_closed_loop(payload)
    loop = state.run_bayesian_closed_loop_to_boundary(
        created["pipeline_id"], {"max_transitions": 8})["state"]
    quick = [run for run in state.runtime_store.list_runs()
             if run.task_spec.labels.get("fidelity") == "quick"]
    full = [run for run in state.runtime_store.list_runs()
            if run.task_spec.labels.get("fidelity") == "full"]
    assert loop["status"] in {"completed", "diagnosis_required"}
    assert quick == []
    assert len(full) == 2 * 3
    assert all(item["mode"] == "calibration_full_replay"
               for item in loop["promotion_history"])


def test_parameter_caused_quick_failures_train_finish_feasibility_model(
        tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROAD_TEST_FAIL_QUICK", "orfs_failure")
    state, design = _state(tmp_path, monkeypatch)
    payload = {**_payload(design["id"]),
               "experiment_key": "quick-failure-negatives", "max_rounds": 2,
               "optimizer_minimum_initial": 100}
    created = state.start_bayesian_closed_loop(payload)
    loop = state.run_bayesian_closed_loop_to_boundary(
        created["pipeline_id"], {"max_transitions": 8})["state"]

    observations = state.optimization_store.observations(loop["study_id"])
    baseline_context = observations[0].context.fingerprint
    failures = [item for item in observations
                if item.failure_category == "orfs_failure"]
    expected_parameters = {spec["name"] for spec in loop["parameter_space"]}
    assert loop["status"] == "completed"
    assert len(observations) == 3 + 2
    assert len(failures) == 2
    assert all(item.status == "failed" and not item.metrics for item in failures)
    assert all(item.context.flow_stage == "finish" for item in failures)
    assert all(item.context.fingerprint == baseline_context for item in failures)
    assert all(set(item.parameters) == expected_parameters for item in failures)
    assert any(event.get("optimizer_observation_id")
               for event in loop["agent_events"]
               if event.get("failure_category") == "orfs_failure")


def test_no_edair_ablation_uses_legacy_kpi_path_and_never_calls_edair(tmp_path, monkeypatch):
    state, design = _state(tmp_path, monkeypatch)

    def forbidden_edair(*_args, **_kwargs):
        raise AssertionError("EDAIR must be disabled by the preregistered ablation")

    monkeypatch.setattr(state, "runtime_edair", forbidden_edair)
    payload = {**_payload(design["id"]),
               "experiment_key": "no-edair-study", "max_rounds": 7,
               "ablation_id": "no_edair"}
    created = state.start_bayesian_closed_loop(payload)
    loop = state.run_bayesian_closed_loop_to_boundary(
        created["pipeline_id"], {"max_transitions": 16})["state"]
    assert loop["status"] in {"completed", "diagnosis_required"}
    assert loop["stall_diagnoses"]
    assert all(item["packet"]["edair_diagnosis_enabled"] is False
               for item in loop["stall_diagnoses"])
    assert all(item["packet"]["evidence_packets"] == []
               for item in loop["stall_diagnoses"])


def test_stateful_no_edair_ablation_never_builds_an_edair_policy_reference(tmp_path, monkeypatch):
    state, design = _state(tmp_path, monkeypatch)

    def forbidden_edair(*_args, **_kwargs):
        raise AssertionError("stateful no_edair must not call runtime_edair")

    monkeypatch.setattr(state, "runtime_edair", forbidden_edair)
    payload = _payload(design["id"])
    payload.update({
        "experiment_key": "stateful-no-edair",
        "optimizer_backend": "stateful-l2-portfolio-v1",
        "max_rounds": 1, "optimizer_minimum_initial": 4,
        "ablation_id": "no_edair",
    })
    loop = state.run_bayesian_closed_loop_to_boundary(
        state.start_bayesian_closed_loop(payload)["pipeline_id"],
        {"max_transitions": 8})["state"]
    proposal = next(item for item in loop["history"] if item["kind"] == "bo_candidate")
    refs = proposal["model_metadata"]["state_tuning"]["evidence_refs"]
    assert not any(ref.startswith("edair:") for ref in refs)


def test_calibrated_quick_proxy_prunes_without_becoming_final_qor(tmp_path, monkeypatch):
    state, design = _state(tmp_path, monkeypatch)
    payload = _payload(design["id"])
    payload.update({
        "experiment_key": "calibrated-multifidelity",
        "max_rounds": 24,
        # Keep the test at the pre-registered search boundary so it exercises
        # promotion rather than the separate stall/repair transition.
        "optimizer_minimum_initial": 100,
    })
    created = state.start_bayesian_closed_loop(payload)
    loop = state.run_bayesian_closed_loop_to_boundary(
        created["pipeline_id"], {"max_transitions": 16})["state"]
    assert loop["status"] == "completed"
    full = [item for item in loop["history"] if item["kind"] == "bo_candidate"]
    quick_only = [item for item in loop["history"] if item["kind"] == "quick_proxy_only"]
    # Two 8-wide batches establish 16 paired quick/full points. The third
    # batch then promotes the policy minimum of four and leaves four honest
    # quick-only records.
    assert len(full) == 20
    assert len(quick_only) == 4
    assert len(loop["proxy_calibration_records"]) == 20
    assert all(item["summary"] is None and item["utility"] is None
               for item in quick_only)
    assert all("no final QoR" in item["claim_boundary"] for item in quick_only)
    assert len(state.optimization_store.observations(loop["study_id"])) == 3 + 20 * 3
    assert len(state.optimization_store.proposals(loop["study_id"])) == 24
    campaigns = [state.multifidelity_store.campaign(
        f"{created['pipeline_id']}-batch-{index}") for index in (1, 2, 3)]
    assert [item["state"] for item in campaigns] == ["completed"] * 3
