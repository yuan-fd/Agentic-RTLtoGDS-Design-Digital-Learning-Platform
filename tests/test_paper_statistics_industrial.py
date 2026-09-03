import pytest

from openroad_platform_analysis.paper_statistics import (
    anytime_hypervolume_summary, baseline_improvement_summary, cliffs_delta,
    empirical_attainment_summary, holm_adjust,
    paired_bootstrap_interval, paired_permutation_test,
)


def test_paired_permutation_uses_cells_not_replica_rows():
    result = paired_permutation_test([.1, .2, .3], seed_material="frozen-protocol")
    assert result["n_pairs"] == 3
    assert result["exact"] is True
    assert result["permutations"] == 8
    assert result["p_value"] == 1 / 8
    assert result["unit"] == "one paired analysis unit"


def test_holm_is_monotone_in_sorted_raw_p_values():
    adjusted = holm_adjust({"a": .01, "b": .04, "c": .03})
    assert adjusted["a"] <= adjusted["c"] <= adjusted["b"]
    assert all(0 <= value <= 1 for value in adjusted.values())


def test_bootstrap_and_cliff_effect_size_are_deterministic():
    first = paired_bootstrap_interval([1, 2, 3, 4], samples=1000, seed_material="x")
    second = paired_bootstrap_interval([1, 2, 3, 4], samples=1000, seed_material="x")
    assert first == second
    assert cliffs_delta([3, 4], [1, 2]) == 1.0
    assert cliffs_delta([1, 2], [3, 4]) == -1.0


def test_statistics_reject_missing_cells_instead_of_silently_dropping_them():
    with pytest.raises(ValueError):
        paired_permutation_test([])


def test_anytime_hv_auc_counts_infeasible_and_quick_only_rounds_honestly():
    result = anytime_hypervolume_summary({"trace": [
        {"configuration_round": 3, "hypervolume": 2.0},
        {"configuration_round": 5, "hypervolume": 3.0},
    ]}, budget=6, checkpoints=(2, 3, 6))
    assert result["auc"] == 0 + 0 + 2 + 2 + 3 + 3
    assert result["normalized_auc"] == pytest.approx(10 / 6)
    assert result["checkpoint_hypervolume"] == {"2": 0, "3": 2, "6": 3}
    assert result["checkpoint_normalized_auc"] == {
        "2": 0, "3": pytest.approx(2 / 3), "6": pytest.approx(10 / 6)}
    assert result["first_positive_round"] == 3


def test_baseline_improvement_is_not_confused_with_positive_hypervolume():
    result = baseline_improvement_summary([
        {"kind": "bo_candidate", "round": 1,
         "summary": {"eligible": True}, "utility": 0.0},
        {"kind": "bo_candidate", "round": 2,
         "summary": {"eligible": False}, "utility": 4.0},
        {"kind": "bo_candidate", "round": 4,
         "summary": {"eligible": True}, "utility": .01},
    ], budget=5, checkpoints=(1, 3, 5))
    assert result["first_feasible_baseline_improving_round"] == 4
    assert result["checkpoint_attained"] == {
        "1": False, "3": False, "5": True}


def test_empirical_attainment_uses_cells_and_keeps_nonattainment():
    result = empirical_attainment_summary(
        [2, None, 5, 1], budget=6, checkpoints=(1, 3, 6))
    assert result["checkpoints"]["1"]["probability"] == .25
    assert result["checkpoints"]["3"]["probability"] == .5
    assert result["checkpoints"]["6"]["probability"] == .75
