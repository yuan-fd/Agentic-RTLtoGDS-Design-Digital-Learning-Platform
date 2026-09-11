#!/usr/bin/env python3
"""Run public PostEDA case -> platform diagnosis -> private derived score."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
for source_root in (ROOT, *(ROOT / "packages" / name / "src" for name in
                            ("contracts", "analysis", "execution", "scheduler"))):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from openroad_platform_analysis import diagnose_posteda_public_case  # noqa: E402
from openroad_platform_contracts import (  # noqa: E402
    EvidencePointer, PostEDADiagnosisScore, RuntimeStatus,
)
from openroad_platform_execution import (  # noqa: E402
    POSTEDA_BENCH_EVALUATE_CAPABILITY, POSTEDA_BENCH_PUBLIC_CAPABILITY,
    PluginRegistry, build_posteda_evaluation_task,
    build_posteda_public_case_task, posteda_bench_plugin_manifest,
)
from openroad_platform_scheduler import RuntimeStore, WorkflowRuntime  # noqa: E402


SOURCE = ROOT / "var/external-sources/posteda-bench-51884e5-clean"
KLAYOUT = Path("/share/home/yuanwenjie/bin/klayout")
NATIVE = ROOT / "var/evidence/posteda-native-diagnostic-20260905-r1/summary.json"
NATIVE_SHA = "daa938e6d951918b891704025b0eabe9cc70222e6de1fcf58a608fcd3df9b365"
LOCK = ROOT / "integrations/posteda_bench/source.lock.json"
TASK_ID = "drc_essential/L1/q1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifacts(view: dict[str, Any]) -> dict[str, tuple[dict, dict]]:
    found = {}
    for stage in view["stages"]:
        for attempt in stage["attempts"]:
            workspace = Path(attempt["workspace"])
            for artifact in attempt["artifacts"]:
                path = (workspace / artifact["store_key"]).resolve()
                if _sha256(path) != artifact["sha256"]:
                    raise ValueError("registered PostEDA artifact changed")
                found[artifact["kind"]] = (
                    {**artifact, "path": str(path),
                     "attempt_id": attempt["attempt_id"]},
                    json.loads(path.read_text()),
                )
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("refusing to overwrite PostEDA platform evidence")
    if _sha256(NATIVE) != NATIVE_SHA or json.loads(NATIVE.read_text()).get(
            "accepted") is not True:
        raise ValueError("accepted native PostEDA smoke is missing or changed")
    output.mkdir(parents=True, exist_ok=True)
    source_status_before = subprocess.check_output(
        ["git", "-C", str(SOURCE), "status", "--porcelain"], text=True)
    manifest = posteda_bench_plugin_manifest(
        source_checkout=SOURCE, klayout_executable=KLAYOUT,
        python_executable=sys.executable)
    runtime = WorkflowRuntime(
        RuntimeStore(output / "runtime.sqlite"), PluginRegistry([manifest]),
        workspace_root=output / "work", worker_id="posteda-acceptance",
        lease_seconds=120)

    public_task = build_posteda_public_case_task(
        project_id="tutorial", task_id=TASK_ID,
        runtime_task_id="posteda-public-q1-acceptance")
    public_run = runtime.submit(
        public_task, capability=POSTEDA_BENCH_PUBLIC_CAPABILITY)
    public_terminal = runtime.execute_once(
        public_run.run_id, on_line=lambda line: print(line, end="", flush=True))
    public_view = runtime.describe(public_run.run_id)
    public_artifacts = _artifacts(public_view)
    artifact, public_case = public_artifacts["benchmark_public_case"]
    native_trace = public_artifacts["benchmark_native_trace"][1]
    target_evidence = EvidencePointer(
        "source:posteda-bench-protocol", _sha256(LOCK))
    diagnosis, prediction = diagnose_posteda_public_case(
        public_case, run_id=public_run.run_id,
        attempt_id=artifact["attempt_id"], artifact_id=artifact["artifact_id"],
        artifact_sha256=artifact["sha256"], target_evidence=target_evidence)
    # Persist the prediction before constructing the scorer TaskSpec.
    prediction_path = output / "sealed_prediction.json"
    prediction_path.write_text(json.dumps(
        prediction.to_dict(), indent=2, ensure_ascii=False) + "\n")
    prediction_sha = _sha256(prediction_path)

    score_task = build_posteda_evaluation_task(
        project_id="tutorial", prediction=prediction,
        runtime_task_id="posteda-score-q1-acceptance")
    score_run = runtime.submit(
        score_task, capability=POSTEDA_BENCH_EVALUATE_CAPABILITY)
    score_terminal = runtime.execute_once(
        score_run.run_id, on_line=lambda line: print(line, end="", flush=True))
    score_view = runtime.describe(score_run.run_id)
    score_artifacts = _artifacts(score_view)
    score_value = score_artifacts["benchmark_diagnosis_score"][1]
    score = PostEDADiagnosisScore.from_dict(score_value)
    evaluation_trace = score_artifacts["benchmark_evaluation_trace"][1]
    source_status_after = subprocess.check_output(
        ["git", "-C", str(SOURCE), "status", "--porcelain"], text=True)

    drc = next(item for item in diagnosis.analyses if item.domain.value == "drc")
    checks = {
        "native_smoke_preceded_platform": NATIVE.stat().st_mtime <=
            Path(artifact["path"]).stat().st_mtime,
        "public_runtime_succeeded": public_terminal.status is RuntimeStatus.SUCCEEDED,
        "public_artifacts_registered": set(public_artifacts) == {
            "benchmark_public_case", "benchmark_native_trace"},
        "native_upstream_parser_used": native_trace["argv"] == [
            "klayout", "-b", "-r", "drc_error_collection.py"],
        "hidden_label_firewall": public_case["hidden_labels_included"] is False
            and "info" not in json.dumps(public_case).lower(),
        "four_domain_diagnosis": len(diagnosis.analyses) == 4,
        "drc_fact_and_headroom": drc.facts[0].metric == "drc_errors"
            and drc.facts[0].value == 1 and drc.headroom[0].margin == -1,
        "drc_blocker_found": drc.blockers == ("drc_errors_target_violated",),
        "typed_safe_decision": prediction.decision.value == "inspect_drc_geometry",
        "prediction_sealed_before_scoring": prediction_sha == _sha256(prediction_path)
            and prediction.hidden_label_accessed is False,
        "score_runtime_succeeded": score_terminal.status is RuntimeStatus.SUCCEEDED,
        "score_artifacts_registered": set(score_artifacts) == {
            "benchmark_diagnosis_score", "benchmark_evaluation_trace"},
        "private_exact_score": score.exact_type_counts and score.exact_total_errors
            and score.evidence_grounded and score.decision_grounded
            and score.diagnostic_score == 1.0,
        "derived_not_official": score.official_metric is False
            and evaluation_trace["official_metric"] is False,
        "hidden_values_not_exported": evaluation_trace["hidden_label_values_exported"] is False,
        "source_unchanged": source_status_before == source_status_after == "",
    }
    summary = {
        "schema_version": 1,
        "kind": "posteda-bench-platform-diagnostic-acceptance",
        "accepted": all(checks.values()),
        "source_lock": {"path": str(LOCK.relative_to(ROOT)),
                        "sha256": _sha256(LOCK)},
        "native_smoke": {"path": str(NATIVE.relative_to(ROOT)),
                         "sha256": NATIVE_SHA},
        "task_id": TASK_ID,
        "public_run_id": public_run.run_id,
        "score_run_id": score_run.run_id,
        "public_case_artifact": public_artifacts["benchmark_public_case"][0],
        "diagnosis_report": diagnosis.to_dict(),
        "sealed_prediction": {"path": "sealed_prediction.json",
                              "sha256": prediction_sha,
                              "value": prediction.to_dict()},
        "score": score.to_dict(),
        "evaluation_trace": evaluation_trace,
        "checks": checks,
        "claim_boundary": (
            "One admitted PostEDA-Bench DRC q1 public artifact was normalized into "
            "the platform four-domain diagnosis and a typed inspect-before-repair "
            "decision, then privately checked against upstream hidden metadata. The "
            "1.0 value is a derived integration diagnostic score, not official "
            "PostEDA-Bench SR/ERR/VRR, repair success, or broad diagnostic accuracy."),
    }
    path = output / "summary.json"
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    digest = _sha256(path)
    (output / "summary.sha256").write_text(f"{digest}  summary.json\n")
    print(json.dumps({"accepted": summary["accepted"], "summary": str(path),
                      "sha256": digest, "public_run_id": public_run.run_id,
                      "score_run_id": score_run.run_id}, indent=2))
    return 0 if summary["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
