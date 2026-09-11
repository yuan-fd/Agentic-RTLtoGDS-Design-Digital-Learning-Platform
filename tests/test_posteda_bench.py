from __future__ import annotations

import importlib.util
import json
import platform
import sys
from pathlib import Path

import pytest

from openroad_platform_analysis import diagnose_posteda_public_case
from openroad_platform_contracts import (
    DiagnosticDecision, EvidencePointer, PostEDADiagnosisPrediction,
    PostEDADiagnosisScore,
)
from openroad_platform_execution import (
    POSTEDA_ADMITTED_TASKS, POSTEDA_BENCH_EVALUATE_CAPABILITY,
    POSTEDA_BENCH_PUBLIC_CAPABILITY, PluginRegistry,
    build_posteda_evaluation_task, build_posteda_public_case_task,
    posteda_bench_plugin_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "drc_essential/L1/q1"


def _pointer() -> EvidencePointer:
    return EvidencePointer("artifact:runtime-public-case", "a" * 64)


def _prediction() -> PostEDADiagnosisPrediction:
    return PostEDADiagnosisPrediction(
        "posteda-prediction-test", TASK_ID, {"WELL.W.1": 1}, 1,
        DiagnosticDecision.INSPECT_DRC_GEOMETRY,
        "Inspect the cited marker geometry before proposing a repair.",
        (_pointer(),), False,
    )


def _adapter_module():
    path = ROOT / "integrations/posteda_bench/posteda_bench_adapter.py"
    spec = importlib.util.spec_from_file_location("tested_posteda_adapter", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_posteda_contract_round_trip_and_hidden_label_firewall():
    prediction = _prediction()
    assert PostEDADiagnosisPrediction.from_dict(prediction.to_dict()) == prediction
    with pytest.raises(ValueError, match="hidden"):
        PostEDADiagnosisPrediction(
            prediction.prediction_id, TASK_ID, {"WELL.W.1": 1}, 1,
            prediction.decision, prediction.rationale, prediction.evidence,
            True).validate()
    score = PostEDADiagnosisScore(
        "posteda-eval-test", TASK_ID, prediction.prediction_id,
        True, True, True, True, 1.0, False,
        ("Derived score, not official SR.",), prediction.evidence)
    assert PostEDADiagnosisScore.from_dict(score.to_dict()) == score


def test_posteda_tasks_are_bounded_and_separate_public_from_private():
    public = build_posteda_public_case_task(
        project_id="tutorial", task_id=TASK_ID, runtime_task_id="posteda-public")
    assert public.inputs == {"mode": "public_case",
                             "benchmark_id": "posteda-bench-51884e5",
                             "task_id": TASK_ID}
    assert "prediction" not in public.inputs
    evaluation = build_posteda_evaluation_task(
        project_id="tutorial", prediction=_prediction(),
        runtime_task_id="posteda-evaluation")
    assert evaluation.inputs["prediction"]["hidden_label_accessed"] is False
    assert evaluation.labels["official_metric"] == "false"
    with pytest.raises(ValueError, match="outside"):
        build_posteda_public_case_task(
            project_id="tutorial", task_id="drc_reasoning/L3/q7")
    assert POSTEDA_ADMITTED_TASKS == (TASK_ID,)


def test_posteda_public_case_maps_to_four_domain_diagnosis():
    public = {
        "schema_version": 1, "kind": "posteda_public_drc_case",
        "task_id": TASK_ID, "prompt": "Inspect the public DRC report.",
        "description": "ASAP7 DRC runset", "top_cell": "top_cell",
        "error_type_counts": {"WELL.W.1": 1}, "total_errors": 1,
        "report_sha256": "b" * 64,
        "native_entrypoint": "drc_error_collection.py via klayout -b -r",
        "hidden_labels_included": False,
    }
    report, prediction = diagnose_posteda_public_case(
        public, run_id="run-public", attempt_id="attempt-public",
        artifact_id="public-case", artifact_sha256="a" * 64,
        target_evidence=EvidencePointer("source:posteda-protocol", "c" * 64))
    assert {analysis.domain.value for analysis in report.analyses} == {
        "timing", "congestion", "drc", "power"}
    drc = next(item for item in report.analyses if item.domain.value == "drc")
    assert drc.facts[0].value == 1
    assert drc.blockers == ("drc_errors_target_violated",)
    assert prediction.error_type_counts == {"WELL.W.1": 1}
    assert prediction.decision is DiagnosticDecision.INSPECT_DRC_GEOMETRY


def test_posteda_manifest_and_static_discovery():
    source = ROOT / "var/external-sources/posteda-bench-51884e5-clean"
    klayout = Path("/share/home/yuanwenjie/bin/klayout")
    manifest = posteda_bench_plugin_manifest(
        source_checkout=source, klayout_executable=klayout,
        python_executable=sys.executable)
    assert manifest.capabilities == (
        POSTEDA_BENCH_PUBLIC_CAPABILITY, POSTEDA_BENCH_EVALUATE_CAPABILITY)
    assert manifest.supported_arch == (platform.machine(),)
    static = PluginRegistry.from_directory(
        ROOT / "integrations/posteda_bench").resolve(
            "posteda-bench", capability=POSTEDA_BENCH_PUBLIC_CAPABILITY)
    assert static.plugin_version == "51884e5f"


def test_adapter_rejects_hidden_or_shell_fields():
    module = _adapter_module()
    request = {
        "schema_version": 1, "plugin": {"plugin_id": "posteda-bench"},
        "task": {"plugin_id": "posteda-bench",
                 "inputs": {"mode": "public_case",
                            "benchmark_id": "posteda-bench-51884e5",
                            "task_id": TASK_ID, "command": "rm -rf /"},
                 "parameters": {"parser": "upstream-klayout-report"}},
    }
    with pytest.raises(ValueError, match="unapproved"):
        module._task(request)
    request["task"]["inputs"].pop("command")
    request["task"]["inputs"]["hidden_info"] = {"init_errors_num": 1}
    with pytest.raises(ValueError, match="unapproved"):
        module._task(request)
