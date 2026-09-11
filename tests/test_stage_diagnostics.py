from __future__ import annotations

import pytest

from openroad_platform_analysis import diagnose_runtime, metric_facts_from_runtime
from openroad_platform_contracts import (
    AnalysisDomain, AnalysisTarget, DiagnosisReport, EvidencePointer,
    StageAnalysis,
)


def _view(*, setup=-0.2, congestion=12.0, drc=3.0, power=0.8):
    artifact = {
        "artifact_id": "report-1", "kind": "report", "sha256": "a" * 64,
        "metadata": {},
    }
    official = {
        "artifact_id": "official-1", "kind": "report", "sha256": "b" * 64,
        "metadata": {
            "runtime_authority": "protected_evaluator",
            "official_qor": True,
            "canonical_metrics": {
                "setup_wns_ns": setup, "setup_tns_ns": -1.0,
                "drc_errors": drc, "power_W": power,
            },
        },
    }
    metrics = [{
        "name": "globalroute__route__congestion__overflow",
        "value": congestion, "unit": "count",
        "source_artifact_id": "report-1", "parser_id": "orfs-route-json-v1",
        "parser_version": "1",
    }, {
        # This forged adapter value must lose to protected canonical QoR.
        "name": "finish__timing__setup__ws", "value": 99.0,
        "source_artifact_id": "report-1", "parser_id": "orfs-finish-json-v1",
        "parser_version": "1",
    }]
    return {
        "run": {"run_id": "run-1", "status": "succeeded"},
        "stages": [{"stage_key": "finish", "attempts": [{
            "attempt_id": "attempt-1", "status": "succeeded",
            "artifacts": [artifact, official], "metrics": metrics,
        }]}],
    }


def _targets():
    source = (EvidencePointer("source:frozen-analysis-policy", "c" * 64),)
    return (
        AnalysisTarget("setup_wns_ns", ">=", 0.0, "ns", source),
        AnalysisTarget("congestion_overflow", "<=", 0.0, "count", source),
        AnalysisTarget("drc_errors", "==", 0.0, "count", source),
        AnalysisTarget("power_W", "<=", 1.0, "W", source),
    )


def test_four_analyzers_separate_facts_headroom_blockers_and_hypotheses():
    report = diagnose_runtime(_view(), targets=_targets())
    assert DiagnosisReport.from_dict(report.to_dict()) == report
    assert {item.domain for item in report.analyses} == set(AnalysisDomain)
    facts = {fact.metric: fact for item in report.analyses for fact in item.facts}
    assert facts["setup_wns_ns"].value == -0.2
    assert facts["setup_wns_ns"].authority == "protected_evaluator"
    assert facts["congestion_overflow"].authority == "runtime_metric"
    margins = {item.metric: item for analysis in report.analyses
               for item in analysis.headroom}
    assert margins["setup_wns_ns"].margin == -0.2
    assert margins["congestion_overflow"].margin == -12.0
    assert margins["drc_errors"].margin == -3.0
    assert margins["power_W"].margin == pytest.approx(0.2)
    assert set(report.blockers) == {
        "setup_wns_ns_target_violated",
        "congestion_overflow_target_violated",
        "drc_errors_target_violated",
    }
    assert {item.statement_id for item in report.hypotheses}
    assert all(item.status == "unconfirmed" for item in report.hypotheses)
    assert all(item.verification_checks for item in report.hypotheses)


def test_missing_metric_or_target_is_unknown_not_synthetic_headroom():
    view = _view()
    view["stages"][0]["attempts"][0]["metrics"] = []
    report = diagnose_runtime(view, targets=_targets()[:1])
    congestion = next(item for item in report.analyses
                      if item.domain is AnalysisDomain.CONGESTION)
    power = next(item for item in report.analyses
                 if item.domain is AnalysisDomain.POWER)
    assert congestion.completeness.value == "unavailable"
    assert congestion.facts == () and congestion.headroom == ()
    assert "No evidence-backed target is supplied for power_W" in power.unknowns[0]
    assert power.headroom == ()
    assert any("power budget" in item for item in report.next_checks)


def test_clean_congestion_is_counter_evidence_not_root_cause_proof():
    report = diagnose_runtime(_view(congestion=0.0, drc=0.0), targets=_targets())
    assert len(report.counter_evidence) == 1
    assert report.counter_evidence[0].status == "counter_evidence"
    assert "does not support global congestion" in report.counter_evidence[0].statement
    assert "localized effects" in report.counter_evidence[0].verification_checks[0]


def test_stage_analysis_round_trip_is_strict():
    report = diagnose_runtime(_view(setup=0.1, congestion=0, drc=0), targets=_targets())
    for analysis in report.analyses:
        assert StageAnalysis.from_dict(analysis.to_dict()) == analysis


def test_only_artifact_backed_parser_metrics_enter_analysis():
    view = _view()
    attempt = view["stages"][0]["attempts"][0]
    attempt["metrics"].append({
        "name": "globalroute__route__congestion__overflow", "value": 999,
        "source_artifact_id": None, "parser_id": None, "parser_version": None,
    })
    _, _, facts, _ = metric_facts_from_runtime(view)
    congestion = [item for item in facts if item.metric == "congestion_overflow"]
    assert len(congestion) == 1 and congestion[0].value == 12.0
