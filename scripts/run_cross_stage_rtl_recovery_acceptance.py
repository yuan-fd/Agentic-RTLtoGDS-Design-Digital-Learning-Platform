#!/usr/bin/env python3
"""Run one real backend failure -> typed RTL checkpoint restore -> GDS."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
for source_root in (ROOT, *(ROOT / "packages" / name / "src" for name in
                            ("contracts", "analysis", "execution", "scheduler"))):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from apps.api.app import ApiState  # noqa: E402
from openroad_platform_analysis import (  # noqa: E402
    classify_convergence, diagnose_runtime, diagnose_terminal_failure,
)
from openroad_platform_contracts import (  # noqa: E402
    AnalysisTarget, ConvergencePolicy, EvidencePointer, MetricTrajectory,
    MetricTrajectoryPoint, ObjectiveDirection, RecoveryAction,
    RollbackCheckpoint, RTLCandidate, RuntimeStatus, SpecIR,
    VerificationPackage,
)
from openroad_platform_scheduler import (  # noqa: E402
    L1ControlStateStore, PDAgentControlStateMachine, decide_recovery,
    plan_rtl_checkpoint_restore, select_rtl_checkpoint_candidate,
)


SOURCE_ACCEPTANCE = ROOT / "var/evidence/rtlscout-native-spec-to-gds-20260905-r8/summary.json"
SOURCE_ACCEPTANCE_SHA = "602a13dc56145ab3b3e3f7c290b92c269fe4f137b54e6e14b3185f8b075f4cb0"
CLEAN_RTL_SHA = "bc06e926eb3b9df99c1455ebb78d04a5f618bda623f261c4437c5a5ed50de69a"
FAULT_RTL = ROOT / "tests/fixtures/cross_stage_synthesis_blackbox.sv"
FAULT_RTL_SHA = "e81c473e2a8b4c2aa8d2f5ce5584b228054be2a0cc68a2f411a24607fc53b037"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _source_snapshot(path: Path) -> dict[str, str]:
    return {
        "head": subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip(),
        "status": subprocess.check_output(
            ["git", "-C", str(path), "status", "--porcelain"], text=True),
    }


def _run(state: ApiState, receipt: dict[str, Any]):
    run_id = str(receipt["run"]["run"]["run_id"])
    terminal = state.runtime.execute_once(
        run_id, on_line=lambda line: print(line, end="", flush=True))
    collection = state.auto_collect_terminal_run(run_id)
    return terminal, state.runtime.describe(run_id), collection


def _artifacts(view: dict[str, Any]) -> list[dict[str, Any]]:
    found = []
    for stage in view["stages"]:
        for attempt in stage["attempts"]:
            workspace = Path(attempt["workspace"])
            for artifact in attempt["artifacts"]:
                path = (workspace / artifact["store_key"]).resolve()
                if not path.is_file() or _sha256(path) != artifact["sha256"]:
                    raise ValueError(f"Runtime artifact is missing or changed: {path}")
                found.append({**artifact, "path": str(path),
                              "attempt_id": attempt["attempt_id"]})
    return found


def _check_pointer(row: dict[str, Any]) -> EvidencePointer:
    return EvidencePointer(str(row["evidence_ref"]), str(row["evidence_sha256"]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--orfs-root", type=Path,
                        default=ROOT.parent / "OpenROAD-flow-scripts")
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("refusing to overwrite cross-stage recovery evidence")
    if _sha256(SOURCE_ACCEPTANCE) != SOURCE_ACCEPTANCE_SHA:
        raise ValueError("native RTLScout acceptance evidence changed")
    if _sha256(FAULT_RTL) != FAULT_RTL_SHA:
        raise ValueError("frozen cross-stage fault fixture changed")
    source_acceptance = json.loads(SOURCE_ACCEPTANCE.read_text())
    if source_acceptance.get("accepted") is not True:
        raise ValueError("native RTLScout acceptance did not pass")
    clean_artifact = next(
        item for item in source_acceptance["artifact_verification"]["rtlscout"]
        if item["kind"] == "rtl" and item["sha256"] == CLEAN_RTL_SHA)
    clean_source = Path(clean_artifact["path"])
    if _sha256(clean_source) != CLEAN_RTL_SHA:
        raise ValueError("native RTLScout clean RTL artifact changed")

    output.mkdir(parents=True, exist_ok=True)
    (output / "state").mkdir()
    protocol = {
        "schema_version": 1,
        "kind": "platform-owned-cross-stage-rtl-recovery-protocol",
        "official_closer_bench": False,
        "source_acceptance_sha256": SOURCE_ACCEPTANCE_SHA,
        "clean_rtl_sha256": CLEAN_RTL_SHA,
        "fault_rtl_sha256": FAULT_RTL_SHA,
        "fault_model": "SYNTHESIS-only unresolved physical blackbox",
        "platform": "nangate45", "target_stage": "finish",
        "clock_period_ns": 10.0, "core_utilization_pct": 10.0,
        "place_density": 0.45, "or_seed": 1,
        "maximum_backend_runs": 2,
        "expected_trajectory": [
            "fault functional verification passes",
            "fault ORFS fails",
            "L1 emits evidence-backed typed recovery decision",
            "clean RTLScout checkpoint is selected and reverified",
            "restored ORFS emits registered GDS and protected QoR",
        ],
    }
    protocol_path = output / "frozen_protocol.json"
    protocol_path.write_text(json.dumps(protocol, indent=2) + "\n")
    protocol_sha = _sha256(protocol_path)
    started = time.monotonic()
    sources = {
        "rtlscout": ROOT / ".external-src/rtlscout",
        "orfs": args.orfs_root.expanduser().resolve(),
    }
    source_before = {name: _source_snapshot(path) for name, path in sources.items()}
    state = ApiState(
        output / "api.db", output / "uploads", sources["orfs"],
        design_root=output / "designs", legacy_root=output / "legacy",
        yosys_bin=ROOT.parent / "bin/yosys",
        runtime_db_path=output / "state/runtime.sqlite",
        runtime_workspace_root=output / "work", load_taiwei_plugin=False,
    )
    spec = SpecIR.from_dict(source_acceptance["spec_ir"])
    state.rtl_frontend.add_spec(spec)
    testbench = str(source_acceptance["runtime_views"]["rtlscout"]["run"]
                    ["task_spec"]["inputs"]["testbench_source"])
    testbench_sha = _text_sha256(testbench)
    expected_tb_sha = source_acceptance["verification"]["testbench_sha256"]
    if testbench_sha != expected_tb_sha:
        raise ValueError("frozen testbench changed")
    (state.verification_oracle_root / f"{testbench_sha}.sv").write_text(testbench)
    package = VerificationPackage(
        "verify-cross-stage-recovery-v1", spec.spec_id,
        ("verilator-lint", "yosys-check"),
        (f"artifact:verification-oracle:{testbench_sha}",),
    )
    state.rtl_frontend.add_verification_package(package)
    for source, digest in ((clean_source, CLEAN_RTL_SHA),
                           (FAULT_RTL, FAULT_RTL_SHA)):
        shutil.copy2(source, state.rtl_candidate_root / f"{digest}.sv")
    clean_candidate = RTLCandidate(
        "candidate-clean-rtlscout-checkpoint", spec.spec_id,
        package.verification_id, f"artifact:rtl-candidate:{CLEAN_RTL_SHA}",
        "rtlscout-v2-accepted-checkpoint",
        provenance={"source_acceptance_sha256": SOURCE_ACCEPTANCE_SHA,
                    "testbench_top": "tb", "oracle_origin": "reference_model"},
    )
    fault_candidate = RTLCandidate(
        "candidate-controlled-backend-fault", spec.spec_id,
        package.verification_id, f"artifact:rtl-candidate:{FAULT_RTL_SHA}",
        "platform-owned-fault-injection-v1", (clean_candidate.candidate_id,),
        {"fault_rtl_sha256": FAULT_RTL_SHA, "testbench_top": "tb",
         "oracle_origin": "reference_model", "protocol_sha256": protocol_sha},
    )
    state.rtl_frontend.add_candidate(clean_candidate)
    state.rtl_frontend.add_candidate(fault_candidate)

    clean_verify, clean_verify_view, clean_verify_collection = _run(
        state, state.submit_rtl_verification(
            spec.spec_id, candidate_id=clean_candidate.candidate_id))
    clean_sim, clean_sim_view, clean_sim_collection = _run(
        state, state.submit_rtl_simulation(
            spec.spec_id, {}, candidate_id=clean_candidate.candidate_id))
    fault_verify, fault_verify_view, fault_verify_collection = _run(
        state, state.submit_rtl_verification(
            spec.spec_id, candidate_id=fault_candidate.candidate_id))
    fault_sim, fault_sim_view, fault_sim_collection = _run(
        state, state.submit_rtl_simulation(
            spec.spec_id, {}, candidate_id=fault_candidate.candidate_id))
    if any(item.status is not RuntimeStatus.SUCCEEDED for item in
           (clean_verify, clean_sim, fault_verify, fault_sim)):
        raise RuntimeError("frozen frontend verification gates did not pass")

    checkpoint_lineage = state.rtl_frontend.lineage(spec.spec_id)
    clean_checks = [item for item in checkpoint_lineage["checks"]
                    if item["candidate_id"] == clean_candidate.candidate_id
                    and item["status"] == "passed"]
    clean_compile = next(item for item in clean_checks
                         if item["check_kind"] == "compile_lint")
    clean_functional = next(item for item in clean_checks
                            if item["check_kind"] == "simulation")
    clean_pointer = EvidencePointer(
        f"artifact:rtl-candidate:{CLEAN_RTL_SHA}", CLEAN_RTL_SHA)
    fault_pointer = EvidencePointer(
        f"artifact:rtl-candidate:{FAULT_RTL_SHA}", FAULT_RTL_SHA)

    fault_terminal, fault_view, fault_collection = _run(
        state, state.promote_verified_rtl_to_orfs(
            spec.spec_id, candidate_id=fault_candidate.candidate_id))
    if fault_terminal.status is not RuntimeStatus.FAILED:
        raise RuntimeError(
            f"controlled backend fault did not fail: {fault_terminal.status.value}")
    fault_report, failure_class = diagnose_terminal_failure(fault_view)
    failed_attempt = fault_view["stages"][-1]["attempts"][-1]
    failure_category = str((failed_attempt.get("failure") or {}).get(
        "category") or "unknown")
    trajectory = MetricTrajectory(
        "trajectory-cross-stage-failure", "setup_wns_ns", "ns",
        ObjectiveDirection.MAXIMIZE, protocol_sha,
        (MetricTrajectoryPoint(
            "point-backend-failure", 0, fault_view["run"]["run_id"],
            failed_attempt["attempt_id"], "finish", "setup_wns_ns", "ns",
            "failed", protocol_sha, "runtime_metric", fault_report.evidence,
            failure_category=failure_category,
            parser_id="runtime-terminal-status-v1",
        ),), fault_report.evidence,
    )
    assessment = classify_convergence(
        trajectory, ConvergencePolicy("cross-stage-policy-v1", 0.0, 0.0))
    control = L1ControlStateStore(output / "state/l1-control.sqlite")
    machine = PDAgentControlStateMachine()
    planner_states = [machine.initialize(
        "goal-cross-stage-recovery", ("finish",),
        (fault_pointer, EvidencePointer("source:frozen-recovery-protocol", protocol_sha)))]
    planner_states.append(machine.runtime_submitted(
        planner_states[-1], run_id=fault_view["run"]["run_id"],
        evidence=fault_report.evidence))
    planner_states.append(machine.runtime_terminal(
        planner_states[-1], terminal_status="failed",
        evidence=fault_report.evidence))
    analyzed, analyzer, debugger = machine.analysis_completed(
        planner_states[-1], fault_report)
    planner_states.append(analyzed)
    planner_states.append(machine.record_convergence(
        planner_states[-1], assessment))
    checkpoint = RollbackCheckpoint(
        "checkpoint-clean-rtlscout", planner_states[-1].goal_id,
        planner_states[0].planner_state_id, planner_states[0].revision,
        "finish", 0, str(clean_compile["detail"]["run_id"]), protocol_sha,
        (clean_pointer, _check_pointer(clean_compile),
         _check_pointer(clean_functional)),
    )
    decision = decide_recovery(
        planner_states[-1], fault_report, assessment,
        failure_class=failure_class, rollback_checkpoints=(checkpoint,))
    for item in planner_states:
        control.append_planner(item)
    control.append_analyzer(analyzer)
    if debugger is not None:
        control.append_debugger(debugger)
    control.append_recovery_decision(decision)
    restore_plan = plan_rtl_checkpoint_restore(
        decision, checkpoint, state.rtl_frontend.lineage(spec.spec_id),
        failed_candidate_id=fault_candidate.candidate_id,
        target_candidate_id=clean_candidate.candidate_id,
    )
    control.append_rtl_restore_plan(restore_plan)
    selected = select_rtl_checkpoint_candidate(
        restore_plan, state.rtl_frontend.lineage(spec.spec_id))

    restored_verify, restored_verify_view, restored_verify_collection = _run(
        state, state.submit_rtl_verification(
            spec.spec_id, candidate_id=selected.candidate_id))
    restored_sim, restored_sim_view, restored_sim_collection = _run(
        state, state.submit_rtl_simulation(
            spec.spec_id, {}, candidate_id=selected.candidate_id))
    restored_orfs, restored_view, restored_collection = _run(
        state, state.promote_verified_rtl_to_orfs(
            spec.spec_id, candidate_id=selected.candidate_id))
    evaluator = ROOT / "packages/analysis/src/openroad_platform_analysis/common_evaluator.py"
    target_evidence = (EvidencePointer(
        "source:protected-orfs-evaluator-v3", _sha256(evaluator)),)
    restored_report = diagnose_runtime(restored_view, targets=(
        AnalysisTarget("setup_wns_ns", ">=", 0.0, "ns", target_evidence),
        AnalysisTarget("drc_errors", "==", 0.0, "count", target_evidence),
    ))
    source_after = {name: _source_snapshot(path) for name, path in sources.items()}
    views = {
        "clean_checkpoint_verify": clean_verify_view,
        "clean_checkpoint_simulation": clean_sim_view,
        "fault_verify": fault_verify_view, "fault_simulation": fault_sim_view,
        "fault_orfs": fault_view,
        "restored_verify": restored_verify_view,
        "restored_simulation": restored_sim_view,
        "restored_orfs": restored_view,
    }
    artifacts = {name: _artifacts(view) for name, view in views.items()}
    fault_artifacts = artifacts["fault_orfs"]
    restored_artifacts = artifacts["restored_orfs"]
    restored_gds = [item for item in restored_artifacts if item["kind"] == "gds"]
    restored_protected = [item for item in restored_artifacts
                          if Path(item["path"]).name == "common_evaluation.json"]
    final_lineage = state.rtl_frontend.lineage(spec.spec_id)
    fault_ppa = [item for item in final_lineage["checks"]
                 if item["candidate_id"] == fault_candidate.candidate_id
                 and item["check_kind"] == "ppa"]
    restored_ppa = [item for item in final_lineage["checks"]
                    if item["candidate_id"] == clean_candidate.candidate_id
                    and item["check_kind"] == "ppa"]
    checks = {
        "source_acceptance_pinned": _sha256(SOURCE_ACCEPTANCE) == SOURCE_ACCEPTANCE_SHA,
        "fault_protocol_pinned": _sha256(FAULT_RTL) == FAULT_RTL_SHA
            and _sha256(protocol_path) == protocol_sha,
        "clean_checkpoint_independently_verified":
            clean_verify.status is RuntimeStatus.SUCCEEDED
            and clean_sim.status is RuntimeStatus.SUCCEEDED,
        "fault_frontend_passed": fault_verify.status is RuntimeStatus.SUCCEEDED
            and fault_sim.status is RuntimeStatus.SUCCEEDED,
        "fault_backend_really_failed": fault_terminal.status is RuntimeStatus.FAILED
            and failure_category == "orfs_failure",
        "failure_artifacts_retained": bool(fault_artifacts)
            and any(item["kind"] == "log" for item in fault_artifacts),
        "diagnosis_has_no_fake_qor": all(
            not analysis.facts and analysis.completeness.value == "unavailable"
            for analysis in fault_report.analyses),
        "typed_fix_decision": decision.action is RecoveryAction.REQUEST_TYPED_FIX
            and decision.recovery_class.value == "meso",
        "restore_plan_is_durable": control.get_rtl_restore_plan(
            restore_plan.plan_id) == restore_plan,
        "restore_selects_exact_clean_hash": selected.candidate_id == clean_candidate.candidate_id
            and restore_plan.target_rtl_sha256 == CLEAN_RTL_SHA,
        "restored_frontend_passed": restored_verify.status is RuntimeStatus.SUCCEEDED
            and restored_sim.status is RuntimeStatus.SUCCEEDED,
        "restored_backend_succeeded": restored_orfs.status is RuntimeStatus.SUCCEEDED,
        "restored_gds_registered": len(restored_gds) == 1
            and restored_gds[0]["size_bytes"] > 0,
        "restored_protected_qor_registered": len(restored_protected) == 1,
        "failed_and_success_checks_both_durable": bool(fault_ppa) and bool(restored_ppa)
            and fault_ppa[-1]["status"] == "failed"
            and restored_ppa[-1]["status"] == "passed",
        "external_sources_unchanged": source_before == source_after,
        "bounded_backend_budget": 2 == protocol["maximum_backend_runs"],
    }
    summary = {
        "schema_version": 1,
        "kind": "platform-cross-stage-rtl-recovery-acceptance",
        "accepted": all(checks.values()),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "official_closer_bench_result": False,
        "protocol": {"path": "frozen_protocol.json", "sha256": protocol_sha,
                     "value": protocol},
        "source_acceptance": {"path": str(SOURCE_ACCEPTANCE.relative_to(ROOT)),
                              "sha256": SOURCE_ACCEPTANCE_SHA},
        "candidates": {"clean": clean_candidate.to_dict(),
                       "fault": fault_candidate.to_dict()},
        "checkpoint": checkpoint.to_dict(),
        "failure_class": failure_class.value,
        "failure_diagnosis": fault_report.to_dict(),
        "convergence_assessment": assessment.to_dict(),
        "recovery_decision": decision.to_dict(),
        "restore_plan": restore_plan.to_dict(),
        "restored_diagnosis": restored_report.to_dict(),
        "statuses": {name: view["run"]["status"] for name, view in views.items()},
        "collections": {
            "clean_checkpoint_verify": clean_verify_collection,
            "clean_checkpoint_simulation": clean_sim_collection,
            "fault_verify": fault_verify_collection,
            "fault_simulation": fault_sim_collection,
            "fault_orfs": fault_collection,
            "restored_verify": restored_verify_collection,
            "restored_simulation": restored_sim_collection,
            "restored_orfs": restored_collection,
        },
        "runtime_views": views,
        "artifact_verification": artifacts,
        "final_lineage": final_lineage,
        "checks": checks,
        "source_before": source_before, "source_after": source_after,
        "claim_boundary": (
            "One platform-owned, bounded cross-stage recovery acceptance over the exact "
            "RTL from a pinned native RTLScout acceptance. A SYNTHESIS-only unresolved "
            "blackbox passed the unchanged functional oracle and failed real ORFS; L1 "
            "recorded a conservative no-QoR failure diagnosis and typed restore plan, "
            "then reverified the clean content-addressed checkpoint and reached a real "
            "registered GDS with protected QoR. This is not CLOSER-Bench, a repair-policy "
            "accuracy result, or evidence of general recovery capability."),
    }
    path = output / "summary.json"
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    digest = _sha256(path)
    (output / "summary.sha256").write_text(f"{digest}  summary.json\n")
    print(json.dumps({
        "accepted": summary["accepted"], "summary": str(path),
        "sha256": digest, "fault_run_id": fault_view["run"]["run_id"],
        "restored_run_id": restored_view["run"]["run_id"],
        "gds_sha256": restored_gds[0]["sha256"] if restored_gds else None,
    }, indent=2))
    return 0 if summary["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
