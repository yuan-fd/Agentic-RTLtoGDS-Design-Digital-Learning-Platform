import pytest

from openroad_platform_analysis import audit_closer_protocol_alignment


def _rtl():
    names = {"native_rtlscout_runtime_succeeded": True,
             "compile_lint_passed": True, "simulation_passed": True,
             "mutation_quality_passed": True, "orfs_finish_succeeded": True,
             "gds_registered_nonempty": True,
             "protected_evaluation_registered": True,
             "upstream_source_unchanged": True}
    views = {name: {"run": {"status": "succeeded"}} for name in (
        "rtlscout", "compile_lint", "simulation", "mutation_quality", "orfs_finish")}
    return {"kind": "rtlscout-native-spec-to-gds-acceptance", "accepted": True,
            "checks": names, "runtime_views": views, "elapsed_seconds": 10,
            "natural_language_spec_sha256": "a" * 64, "spec_ir_sha256": "b" * 64}


def _recovery():
    return {"kind": "l1-typed-recovery-policy-acceptance", "accepted": True,
            "scenarios": {"blocker": {}, "regression": {}},
            "checks": {"real_blocker_requests_typed_fix": True,
                       "divergence_selects_evidence_checkpoint": True,
                       "all_decisions_durable": True,
                       "no_shell_or_parameter_payload": True}}


def _executed_recovery():
    checks = {name: True for name in (
        "fault_frontend_passed", "fault_backend_really_failed",
        "diagnosis_has_no_fake_qor", "typed_fix_decision",
        "restore_plan_is_durable", "restore_selects_exact_clean_hash",
        "restored_frontend_passed", "restored_backend_succeeded",
        "restored_gds_registered", "restored_protected_qor_registered",
        "failed_and_success_checks_both_durable",
    )}
    return {"kind": "platform-cross-stage-rtl-recovery-acceptance",
            "accepted": True, "official_closer_bench_result": False,
            "checks": checks}


def test_alignment_is_honest_about_unexecuted_cross_stage_recovery():
    result = audit_closer_protocol_alignment(_rtl(), _recovery())
    by_name = {item["criterion"]: item for item in result["criteria"]}
    assert by_name["one_real_spec_to_gds_path"]["status"] == "met"
    assert by_name["typed_cross_stage_recovery_policy"]["status"] == "met"
    assert by_name["executed_cross_stage_recovery_and_rollback_precision"][
        "status"] == "missing"
    assert result["official_closer_bench_result"] is False
    assert result["ready_for_official_benchmark_claim"] is False


def test_alignment_rejects_unaccepted_or_wrong_evidence():
    broken = _rtl(); broken["accepted"] = False
    with pytest.raises(ValueError, match="accepted"):
        audit_closer_protocol_alignment(broken, _recovery())
    recovery = _recovery(); recovery["kind"] = "unknown"
    with pytest.raises(ValueError, match="recovery"):
        audit_closer_protocol_alignment(_rtl(), recovery)


def test_alignment_counts_bounded_executed_recovery_without_official_claim():
    result = audit_closer_protocol_alignment(
        _rtl(), _recovery(), _executed_recovery())
    by_name = {item["criterion"]: item for item in result["criteria"]}
    assert by_name["executed_cross_stage_recovery_and_rollback_precision"][
        "status"] == "met"
    assert result["counts"] == {"met": 5, "partial": 2, "missing": 3}
    assert result["official_closer_bench_result"] is False
    assert result["ready_for_official_benchmark_claim"] is False

    invalid = _executed_recovery()
    invalid["official_closer_bench_result"] = True
    with pytest.raises(ValueError, match="non-official"):
        audit_closer_protocol_alignment(_rtl(), _recovery(), invalid)
