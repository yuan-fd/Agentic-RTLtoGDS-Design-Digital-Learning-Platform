from openroad_platform_analysis.target_feasibility import (
    aggregate_target_feasibility, derive_admitted_target_domain,
    build_anchor_perturbation_plan, derive_target_execution_envelope,
)


def test_anchor_plan_is_one_factor_deduplicated_and_replicated():
    cases = build_anchor_perturbation_plan(
        anchor={"util": 20, "dpo": 1},
        levels={"util": [20, 30, 40], "dpo": [0, 1]},
        seeds=[101, 211, 307],
    )
    assert len(cases) == 12  # baseline + util=30/40 + dpo=0, each three times
    assert {case["or_seed"] for case in cases} == {101, 211, 307}
    assert sum(case["kind"] == "baseline" for case in cases) == 3
    for case in cases:
        changes = sum(case["parameters"][key] != value
                      for key, value in {"util": 20, "dpo": 1}.items())
        assert changes <= 1


def test_aggregate_only_releases_replicated_feasible_dimensions():
    anchor = {"util": 20, "dpo": 1}
    cases = build_anchor_perturbation_plan(
        anchor=anchor, levels={"util": [20, 30, 40], "dpo": [0, 1]},
        seeds=[101, 211, 307],
    )
    outcomes = {}
    for case in cases:
        feasible = not (case["parameter"] == "util" and case["requested_value"] == 40)
        outcomes[case["case_id"]] = {
            "status": "succeeded" if feasible else "failed",
            "evaluator_feasible": feasible,
        }
    report = aggregate_target_feasibility(
        anchor=anchor, cases=cases, outcomes=outcomes, required_seeds=[101, 211, 307],
    )
    assert [item["parameter"] for item in report["dimensions"]] == ["dpo", "util"]
    util = next(item for item in report["dimensions"] if item["parameter"] == "util")
    assert util["observed_feasible_values"] == [20, 30]
    assert report["fixed_parameters"] == {}


def test_aggregate_fails_closed_without_replicated_anchor():
    cases = build_anchor_perturbation_plan(
        anchor={"util": 20}, levels={"util": [20, 30]}, seeds=[101, 211, 307],
    )
    outcomes = {case["case_id"]: {"status": "failed", "evaluator_feasible": False}
                for case in cases}
    try:
        aggregate_target_feasibility(
            anchor={"util": 20}, cases=cases, outcomes=outcomes,
            required_seeds=[101, 211, 307],
        )
    except ValueError as error:
        assert "anchor baseline" in str(error)
    else:
        raise AssertionError("an infeasible anchor must fail closed")


def test_derived_domain_preserves_observed_values_and_fixes_other_knobs():
    anchor = {"util": 20, "dpo": 1}
    cases = build_anchor_perturbation_plan(
        anchor=anchor, levels={"util": [20, 30], "dpo": [0, 1]}, seeds=[101, 211, 307],
    )
    outcomes = {case["case_id"]: {"status": "succeeded", "evaluator_feasible": True}
                for case in cases}
    report = aggregate_target_feasibility(
        anchor=anchor, cases=cases, outcomes=outcomes, required_seeds=[101, 211, 307],
    )
    domain = derive_admitted_target_domain(report, required_parameters=["util", "dpo"])
    assert domain["search_parameter_names"] == ["dpo", "util"]
    assert domain["admissible_values"] == {"dpo": [0, 1], "util": [20, 30]}
    assert domain["fixed_parameters"] == {}


def test_execution_envelope_keeps_verified_values_separate_from_interpolated_candidates():
    anchor = {"util": 20, "lb": .425}
    cases = build_anchor_perturbation_plan(
        anchor=anchor, levels={"util": [20, 30], "lb": [.425, .426]}, seeds=[101, 211, 307],
    )
    outcomes = {case["case_id"]: {"status": "succeeded", "evaluator_feasible": True}
                for case in cases}
    report = aggregate_target_feasibility(
        anchor=anchor, cases=cases, outcomes=outcomes, required_seeds=[101, 211, 307],
    )
    envelope = derive_target_execution_envelope(
        report, required_parameters=["util", "lb"], interpolated_steps={"lb": ".0005"},
    )
    assert envelope["kind"] == "target-execution-envelope-v1"
    assert envelope["verified_values"]["lb"] == [.425, .426]
    assert envelope["admissible_values"]["lb"] == [.425, .4255, .426]
    assert envelope["execution_value_derivations"]["lb"]["not_preflight_feasible_claim"] is True
