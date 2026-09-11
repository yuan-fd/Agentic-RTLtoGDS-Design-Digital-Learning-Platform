"""Non-claiming readiness audit against public CLOSER-Bench paper criteria."""

from __future__ import annotations

from typing import Any, Mapping


def audit_closer_protocol_alignment(
    rtl_to_gds_evidence: Mapping[str, Any],
    recovery_evidence: Mapping[str, Any],
    executed_recovery_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify evidence coverage without pretending to run CLOSER-Bench."""
    if (rtl_to_gds_evidence.get("kind") != "rtlscout-native-spec-to-gds-acceptance"
            or rtl_to_gds_evidence.get("accepted") is not True):
        raise ValueError("accepted native RTLScout-to-GDS evidence is required")
    if (recovery_evidence.get("kind") != "l1-typed-recovery-policy-acceptance"
            or recovery_evidence.get("accepted") is not True):
        raise ValueError("accepted typed recovery evidence is required")
    if executed_recovery_evidence is not None and (
            executed_recovery_evidence.get("kind") !=
            "platform-cross-stage-rtl-recovery-acceptance"
            or executed_recovery_evidence.get("accepted") is not True
            or executed_recovery_evidence.get("official_closer_bench_result") is not False):
        raise ValueError("accepted non-official executed recovery evidence is required")
    views = rtl_to_gds_evidence.get("runtime_views")
    checks = rtl_to_gds_evidence.get("checks")
    scenarios = recovery_evidence.get("scenarios")
    recovery_checks = recovery_evidence.get("checks")
    executed_checks = ((executed_recovery_evidence or {}).get("checks") or {})
    if not all(isinstance(item, Mapping) for item in (views, checks, scenarios,
                                                       recovery_checks)):
        raise ValueError("alignment evidence is structurally incomplete")
    expected_runs = {"rtlscout", "compile_lint", "simulation",
                     "mutation_quality", "orfs_finish"}
    recorded = expected_runs <= set(views)
    all_terminal = recorded and all(
        (views[name].get("run") or {}).get("status") == "succeeded"
        for name in expected_runs)
    immutable = bool(
        rtl_to_gds_evidence.get("natural_language_spec_sha256")
        and rtl_to_gds_evidence.get("spec_ir_sha256")
        and checks.get("upstream_source_unchanged"))
    criteria = (
        {
            "criterion": "one_real_spec_to_gds_path",
            "status": "met" if all_terminal else "missing",
            "evidence": sorted(expected_runs) if all_terminal else [],
            "note": "One native RTLScout, verification and ORFS/GDS path is complete.",
        },
        {
            "criterion": "matched_stage_pairs_A_B_C",
            "status": "missing",
            "evidence": [],
            "note": "The same trace contains stages but is not three independently budgeted matched tasks.",
        },
        {
            "criterion": "shared_hidden_conditions_and_pristine_oracle",
            "status": "missing",
            "evidence": [],
            "note": "The frozen public oracle is real, but no released CLOSER hidden workload/corner/floorplan package exists.",
        },
        {
            "criterion": "tool_invocation_and_artifact_provenance",
            "status": "met" if recorded and immutable else "partial",
            "evidence": sorted(expected_runs) if recorded else [],
            "note": "Runtime run IDs, attempts, registered artifacts and hashes are retained.",
        },
        {
            "criterion": "validity_gates_and_final_quality",
            "status": "met" if all(checks.get(name) for name in (
                "compile_lint_passed", "simulation_passed", "mutation_quality_passed",
                "orfs_finish_succeeded", "gds_registered_nonempty",
                "protected_evaluation_registered")) else "partial",
            "evidence": ["rtlscout-native-spec-to-gds-acceptance"],
            "note": "Functional, mutation, physical and protected QoR gates passed for one design.",
        },
        {
            "criterion": "anytime_reward_and_first_feasible_trajectory",
            "status": "partial",
            "evidence": ["ordered Runtime views"],
            "note": "Ordered events exist, but no frozen cross-stage reward/AUC schema is available.",
        },
        {
            "criterion": "tool_cost_and_equal_budget_accounting",
            "status": "partial" if rtl_to_gds_evidence.get("elapsed_seconds") else "missing",
            "evidence": ["elapsed_seconds"] if rtl_to_gds_evidence.get("elapsed_seconds") else [],
            "note": "Wall time is retained; matched low/medium/high budgets and equal A+B versus C cost are absent.",
        },
        {
            "criterion": "typed_cross_stage_recovery_policy",
            "status": "met" if all(recovery_checks.get(name) for name in (
                "real_blocker_requests_typed_fix", "divergence_selects_evidence_checkpoint",
                "all_decisions_durable", "no_shell_or_parameter_payload")) else "partial",
            "evidence": sorted(scenarios),
            "note": "Failure classification and proposals are durable and evidence-backed.",
        },
        {
            "criterion": "executed_cross_stage_recovery_and_rollback_precision",
            "status": "met" if all(executed_checks.get(name) for name in (
                "fault_frontend_passed", "fault_backend_really_failed",
                "diagnosis_has_no_fake_qor", "typed_fix_decision",
                "restore_plan_is_durable", "restore_selects_exact_clean_hash",
                "restored_frontend_passed", "restored_backend_succeeded",
                "restored_gds_registered", "restored_protected_qor_registered",
                "failed_and_success_checks_both_durable",
            )) else "missing",
            "evidence": (["platform-cross-stage-rtl-recovery-acceptance"]
                         if executed_recovery_evidence is not None else []),
            "note": ("One platform-owned bounded backend-failure to verified RTL "
                     "checkpoint restore and successful GDS trajectory is executed; "
                     "it is not an official CLOSER task or oracle result."
                     if executed_recovery_evidence is not None else
                     "Current recovery acceptance proposes but deliberately does not "
                     "execute a fix or rollback."),
        },
        {
            "criterion": "repeated_trials_invalid_run_manifest_and_confidence",
            "status": "missing",
            "evidence": [],
            "note": "One accepted trace cannot provide repeated-trial statistics or an official invalid-run manifest.",
        },
    )
    counts = {status: sum(item["status"] == status for item in criteria)
              for status in ("met", "partial", "missing")}
    return {
        "schema_version": 1,
        "kind": "closer-paper-protocol-alignment-audit",
        "protocol_alignment_only": True,
        "official_closer_bench_result": False,
        "criteria": list(criteria),
        "counts": counts,
        "ready_for_official_benchmark_claim": counts["missing"] == 0
            and counts["partial"] == 0,
        "recommendation": (
            "Keep the official CLOSER-Bench gate closed. The internal executed "
            "cross-stage recovery gap is closed for one bounded fault; rerun the "
            "official stage-paired protocol only when source/tasks/oracles exist."
            if executed_recovery_evidence is not None else
            "Keep the official CLOSER-Bench gate closed. Add one real backend-failure "
            "to RTL-level fix and successful reimplementation trajectory internally, "
            "then rerun the official stage-paired release when source/oracles exist."),
    }
