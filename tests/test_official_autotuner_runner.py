from pathlib import Path
import importlib.util
import json

import pytest


def _module():
    path = Path(__file__).resolve().parents[1] / "scripts/run_official_autotuner_baseline.py"
    spec = importlib.util.spec_from_file_location("official_runner", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_trial_parser_rejects_upstream_error_penalty(tmp_path):
    root = tmp_path / "experiment"
    bad = root / "variant-bad-ray"; bad.mkdir(parents=True)
    (bad / "result.json").write_text(json.dumps({"trial_id": "bad", "metric": 9e99}) + "\n")
    good = root / "variant-good-ray"; good.mkdir()
    (good / "result.json").write_text(
        json.dumps({"trial_id": "good", "metric": 3.0, "num_drc": 0}) + "\n")
    rows = _module()._trial_results(root)
    assert [row["accepted_by_upstream_metric"] for row in rows] == [False, True]


def test_official_runtime_evidence_must_be_finite_and_positive():
    module = _module()
    assert module._validated_runtime_seconds(
        12.5, source="ray_result.time_total_s") == 12.5
    for invalid in (None, 0, -1, float("nan"), True):
        with pytest.raises(ValueError, match="runtime evidence"):
            module._validated_runtime_seconds(
                invalid, source="ray_result.time_total_s")


def test_upstream_rejected_trial_counts_in_budget_without_replay(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.setattr(module, "_official_tunable_variables", lambda _: set())
    rows = module._common_evaluate_trials(
        trials=[{
            "trial_id": "bad", "accepted_by_upstream_metric": False,
            "path": str(tmp_path / "missing-result.json"),
        }],
        artifact_root=tmp_path / "artifacts", output=tmp_path / "output",
        orfs_root=tmp_path / "orfs", platform="asap7",
        logical_design="ibex", execution_design="opv2_ibex_deadbeef",
        generated_design={"identity_sha256": "a" * 64, "clock_period_ns": 1.468},
        fairness_config_sha256="b" * 64, optimizer_seed=1103,
        or_seeds=[101, 211, 307], openroad_threads=12, timeout_hours=1,
        controlled_environment={},
    )
    assert rows[0]["common_evaluations"] == []
    assert rows[0]["common_evaluation"]["status"] == \
        "not_required_upstream_rejected"
    assert rows[0]["common_evaluation"]["all_feasible"] is False


def test_warm_start_is_uncharged_and_candidate_rounds_are_contiguous():
    module = _module()
    baseline = {"CORE_UTILIZATION": 40, "PLACE_DENSITY_LB_ADDON": .2}
    rows, errors = module._annotate_warm_start([
        {"trial_id": "candidate", "parameters": {
            "CORE_UTILIZATION": 50, "PLACE_DENSITY_LB_ADDON": .1}},
        {"trial_id": "baseline", "parameters": {
            "CORE_UTILIZATION": 40.0, "PLACE_DENSITY_LB_ADDON": .2}},
        {"trial_id": "candidate-2", "parameters": {
            "CORE_UTILIZATION": 60, "PLACE_DENSITY_LB_ADDON": .3}},
    ], baseline)
    assert errors == []
    assert [(row["budget_role"], row["logical_round"]) for row in rows] == [
        ("logical_candidate", 1), ("warm_start_baseline", None),
        ("logical_candidate", 2),
    ]
