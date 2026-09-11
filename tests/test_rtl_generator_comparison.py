from apps.api.app import ApiState


def test_rtl_generator_comparison_groups_checks_and_qor():
    state = object.__new__(ApiState)
    state.get_rtl_lineage = lambda *args, **kwargs: {
        "spec": {"spec_id": "spec-1"},
        "candidates": [
            {"candidate_id": "candidate-direct", "generator": "direct-llm-v1", "verification_id": "v1"},
            {"candidate_id": "candidate-scout", "generator": "rtlscout-v2", "verification_id": "v1"},
        ],
        "checks": [
            {"candidate_id": "candidate-direct", "check_kind": "simulation", "status": "passed", "detail": {"metrics": {"area_um2": 10}}},
            {"candidate_id": "candidate-scout", "check_kind": "simulation", "status": "failed", "detail": {}},
        ],
    }
    result = state.rtl_candidate_comparison("spec-1")
    assert result["generators"] == ["direct-llm-v1", "rtlscout-v2"]
    assert result["candidates"][0]["functional_status"] == "passed"
    assert result["candidates"][0]["qor"] == [{"area_um2": 10}]
    assert result["candidates"][1]["functional_status"] == "not_evaluated"
