"""Deterministic timing/congestion/DRC/power analysis over Runtime facts.

The module does not read a workspace, execute a tool, infer a root cause with
an LLM, or recommend optimizer parameters. It normalizes only Runtime-stored
metrics and protected-evaluator metadata that already cite registered
artifacts, then compares them with explicitly evidenced targets.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence

from openroad_platform_contracts import (
    AnalysisCompleteness, AnalysisDomain, AnalysisTarget, DiagnosisReport,
    DiagnosticStatement, EvidencePointer, Headroom, MetricFact, StageAnalysis,
    RuntimeFailureClass,
)


_ALIASES = {
    "finish__timing__setup__ws": "setup_wns_ns",
    "finish__timing__setup__tns": "setup_tns_ns",
    "finish__timing__hold__ws": "hold_wns_ns",
    "finish__timing__hold__tns": "hold_tns_ns",
    "detailedroute__timing__setup__ws": "setup_wns_ns",
    "detailedroute__timing__setup__tns": "setup_tns_ns",
    "detailedroute__timing__hold__ws": "hold_wns_ns",
    "detailedroute__timing__hold__tns": "hold_tns_ns",
    "finish__power__total": "power_W",
    "detailedroute__power__total": "power_W",
    "detailedroute__route__drc_errors": "drc_errors",
    "finish__route__drc_errors": "drc_errors",
    "globalroute__route__congestion__overflow": "congestion_overflow",
    "detailedroute__route__congestion__overflow": "congestion_overflow",
}

_DOMAIN_METRICS = {
    AnalysisDomain.TIMING: frozenset({
        "setup_wns_ns", "setup_tns_ns", "hold_wns_ns", "hold_tns_ns",
    }),
    AnalysisDomain.CONGESTION: frozenset({
        "congestion_overflow", "grt_overflow_iterations",
    }),
    AnalysisDomain.DRC: frozenset({"drc_errors", "antenna_violations"}),
    AnalysisDomain.POWER: frozenset({"power_W"}),
}

_PRIMARY = {
    AnalysisDomain.TIMING: "setup_wns_ns",
    AnalysisDomain.CONGESTION: "congestion_overflow",
    AnalysisDomain.DRC: "drc_errors",
    AnalysisDomain.POWER: "power_W",
}

_UNITS = {
    "setup_wns_ns": "ns", "setup_tns_ns": "ns",
    "hold_wns_ns": "ns", "hold_tns_ns": "ns",
    "power_W": "W", "drc_errors": "count",
    "antenna_violations": "count", "congestion_overflow": "count",
    "grt_overflow_iterations": "count",
}


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str,
    ).encode()).hexdigest()


def _id(prefix: str, value: Any) -> str:
    return f"{prefix}-{_digest(value)[:20]}"


def _pointer(artifact: Mapping[str, Any]) -> EvidencePointer:
    artifact_id, sha256 = artifact.get("artifact_id"), artifact.get("sha256")
    if (not isinstance(artifact_id, str) or not artifact_id
            or not isinstance(sha256, str) or len(sha256) != 64):
        raise ValueError("Runtime artifact lacks identity or SHA-256")
    return EvidencePointer(f"artifact:runtime-{artifact_id}", sha256)


def _canonical_name(raw: str) -> str | None:
    if raw in {name for names in _DOMAIN_METRICS.values() for name in names}:
        return raw
    if raw in _ALIASES:
        return _ALIASES[raw]
    suffixes = (
        ("timing__setup__ws", "setup_wns_ns"),
        ("timing__setup__tns", "setup_tns_ns"),
        ("timing__hold__ws", "hold_wns_ns"),
        ("timing__hold__tns", "hold_tns_ns"),
        ("power__total", "power_W"),
        ("route__drc_errors", "drc_errors"),
        ("antenna__violating__nets", "antenna_violations"),
        ("route__congestion__overflow", "congestion_overflow"),
        ("overflow_iterations", "grt_overflow_iterations"),
    )
    return next((canonical for suffix, canonical in suffixes
                 if raw.endswith(suffix)), None)


def _domain(metric: str) -> AnalysisDomain:
    return next(domain for domain, names in _DOMAIN_METRICS.items()
                if metric in names)


def _stage(raw_name: str, metric: str) -> str:
    prefix = raw_name.split("__", 1)[0].lower()
    if prefix in {"finish", "detailedroute", "globalroute", "route", "cts", "place"}:
        return {"detailedroute": "route", "globalroute": "route"}.get(prefix, prefix)
    return "finish" if metric in {"setup_wns_ns", "setup_tns_ns", "hold_wns_ns",
                                  "hold_tns_ns", "power_W"} else "route"


def metric_facts_from_runtime(runtime_view: Mapping[str, Any]) -> tuple[str, str, tuple[MetricFact, ...], EvidencePointer]:
    """Extract evidence-backed canonical facts from one Runtime describe view."""
    run = runtime_view.get("run")
    if not isinstance(run, Mapping) or not isinstance(run.get("run_id"), str):
        raise ValueError("expected a Runtime describe view")
    run_id = run["run_id"]
    artifacts: dict[str, Mapping[str, Any]] = {}
    attempts = []
    for stage in runtime_view.get("stages", ()):
        for attempt in stage.get("attempts", ()):
            attempts.append(attempt)
            for artifact in attempt.get("artifacts", ()):
                if isinstance(artifact.get("artifact_id"), str):
                    artifacts[artifact["artifact_id"]] = artifact
    terminal = [item for item in attempts if item.get("status") in {
        "succeeded", "failed", "cancelled", "timed_out", "lost"}]
    if not terminal:
        raise ValueError("Runtime view has no terminal attempt")
    attempt_id = str(terminal[-1].get("attempt_id"))
    run_evidence = EvidencePointer(f"run:{run_id}", _digest({
        "run_id": run_id, "status": run.get("status"),
        "attempt_ids": [item.get("attempt_id") for item in terminal],
    }))

    selected: dict[str, MetricFact] = {}
    # Protected-evaluator facts outrank adapter metrics for canonical QoR.
    for artifact in artifacts.values():
        metadata = artifact.get("metadata")
        if (not isinstance(metadata, Mapping)
                or metadata.get("runtime_authority") != "protected_evaluator"
                or metadata.get("official_qor") is not True
                or not isinstance(metadata.get("canonical_metrics"), Mapping)):
            continue
        evidence = (_pointer(artifact),)
        for metric, value in metadata["canonical_metrics"].items():
            canonical = _canonical_name(str(metric))
            if canonical is None or isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            number = float(value)
            if not math.isfinite(number):
                continue
            payload = (run_id, attempt_id, canonical, number, "protected_evaluator")
            selected[canonical] = MetricFact(
                _id("fact", payload), _domain(canonical),
                _stage(str(metric), canonical), canonical, number,
                _UNITS[canonical], "protected_evaluator", evidence,
            )

    for attempt in terminal:
        for row in attempt.get("metrics", ()):
            raw_name = row.get("name")
            canonical = _canonical_name(raw_name) if isinstance(raw_name, str) else None
            if canonical is None or canonical in selected:
                continue
            value = row.get("value")
            parser_id = row.get("parser_id")
            source_id = row.get("source_artifact_id")
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not isinstance(parser_id, str) or not parser_id
                    or source_id not in artifacts):
                continue
            number = float(value)
            if not math.isfinite(number):
                continue
            evidence = (_pointer(artifacts[source_id]),)
            payload = (run_id, attempt.get("attempt_id"), canonical, number,
                       parser_id, row.get("parser_version"))
            selected[canonical] = MetricFact(
                _id("fact", payload), _domain(canonical),
                _stage(raw_name, canonical), canonical, number,
                str(row.get("unit") or _UNITS[canonical]), "runtime_metric",
                evidence, parser_id, str(row.get("parser_version") or "unknown"),
            )
    facts = tuple(sorted(selected.values(), key=lambda item: item.metric))
    return run_id, attempt_id, facts, run_evidence


def _headroom(fact: MetricFact, target: AnalysisTarget) -> Headroom:
    if fact.unit != target.unit:
        raise ValueError(f"target unit does not match {fact.metric}")
    margin = (fact.value - target.threshold if target.operator == ">=" else
              target.threshold - fact.value if target.operator == "<=" else
              -abs(fact.value - target.threshold))
    return Headroom(
        fact.metric, target.operator, fact.value, target.threshold, margin,
        fact.unit, "satisfied" if margin >= 0 else "violated",
        tuple(dict.fromkeys((*fact.evidence, *target.evidence))),
    )


def analyze_domain(run_id: str, attempt_id: str, facts: Sequence[MetricFact],
                   run_evidence: EvidencePointer, domain: AnalysisDomain,
                   targets: Sequence[AnalysisTarget]) -> StageAnalysis:
    domain_facts = tuple(item for item in facts if item.domain is domain)
    by_target = {item.metric: item for item in targets}
    matched = tuple(_headroom(fact, by_target[fact.metric])
                    for fact in domain_facts if fact.metric in by_target)
    primary = _PRIMARY[domain]
    completeness = (AnalysisCompleteness.COMPLETE
                    if any(item.metric == primary for item in domain_facts)
                    else AnalysisCompleteness.PARTIAL if domain_facts
                    else AnalysisCompleteness.UNAVAILABLE)
    blockers = tuple(f"{item.metric}_target_violated" for item in matched
                     if item.status == "violated")
    unknowns = []
    if completeness is AnalysisCompleteness.UNAVAILABLE:
        unknowns.append(
            f"No artifact-backed {primary} metric is registered in this Runtime run.")
    elif primary not in by_target:
        unknowns.append(
            f"No evidence-backed target is supplied for {primary}; headroom is unknown.")
    for fact in domain_facts:
        if fact.metric != primary and fact.metric not in by_target:
            unknowns.append(f"No evidence-backed target is supplied for {fact.metric}.")
    evidence = tuple(dict.fromkeys(
        (run_evidence, *(pointer for fact in domain_facts for pointer in fact.evidence),
         *(pointer for item in matched for pointer in item.evidence))))
    stage = ({fact.stage for fact in domain_facts}.pop()
             if len({fact.stage for fact in domain_facts}) == 1 else
             "cross_stage" if domain_facts else
             "route" if domain in {AnalysisDomain.CONGESTION, AnalysisDomain.DRC}
             else "finish")
    analysis = StageAnalysis(
        _id("analysis", (run_id, attempt_id, domain.value,
                         [item.to_dict() for item in domain_facts],
                         [item.to_dict() for item in matched])),
        run_id, attempt_id, domain, stage, completeness, domain_facts, matched,
        blockers, tuple(unknowns), evidence,
    )
    analysis.validate()
    return analysis


def diagnose_runtime(runtime_view: Mapping[str, Any], *,
                     targets: Sequence[AnalysisTarget] = ()) -> DiagnosisReport:
    """Build four analyses and conservative cross-domain diagnostic statements."""
    for target in targets:
        target.validate()
    if len({item.metric for item in targets}) != len(targets):
        raise ValueError("analysis targets must be unique by metric")
    run_id, attempt_id, facts, run_evidence = metric_facts_from_runtime(runtime_view)
    analyses = tuple(analyze_domain(
        run_id, attempt_id, facts, run_evidence, domain, targets)
        for domain in AnalysisDomain)
    fact_by_metric = {fact.metric: fact for fact in facts}
    headroom = {item.metric: item for analysis in analyses for item in analysis.headroom}
    hypotheses = []
    counter = []
    timing_bad = headroom.get("setup_wns_ns") and headroom["setup_wns_ns"].status == "violated"
    congestion_bad = headroom.get("congestion_overflow") and headroom["congestion_overflow"].status == "violated"
    congestion_clean = headroom.get("congestion_overflow") and headroom["congestion_overflow"].status == "satisfied"
    drc_bad = headroom.get("drc_errors") and headroom["drc_errors"].status == "violated"
    if timing_bad and congestion_bad:
        basis = (fact_by_metric["setup_wns_ns"], fact_by_metric["congestion_overflow"])
        hypotheses.append(DiagnosticStatement(
            _id("hypothesis", (run_id, "congestion_timing")),
            "Measured routing overflow may contribute to the measured setup deficit.",
            tuple(item.fact_id for item in basis),
            ("Correlate critical-path locations with congestion regions.",
             "Compare timing after a Policy-approved congestion intervention."),
            tuple(dict.fromkeys(pointer for item in basis for pointer in item.evidence)),
        ))
    if drc_bad and congestion_bad:
        basis = (fact_by_metric["drc_errors"], fact_by_metric["congestion_overflow"])
        hypotheses.append(DiagnosticStatement(
            _id("hypothesis", (run_id, "congestion_drc")),
            "Measured routing overflow may contribute to the measured DRC violations.",
            tuple(item.fact_id for item in basis),
            ("Classify DRC markers by type and location.",
             "Check overlap between DRC markers and congestion regions."),
            tuple(dict.fromkeys(pointer for item in basis for pointer in item.evidence)),
        ))
    if timing_bad and congestion_clean:
        basis = (fact_by_metric["setup_wns_ns"], fact_by_metric["congestion_overflow"])
        counter.append(DiagnosticStatement(
            _id("counter", (run_id, "global_congestion_not_supported")),
            "The reported global overflow does not support global congestion as the setup root cause.",
            tuple(item.fact_id for item in basis),
            ("Inspect path-level delay composition and local congestion before excluding localized effects.",),
            tuple(dict.fromkeys(pointer for item in basis for pointer in item.evidence)),
            status="counter_evidence",
        ))
    blockers = tuple(dict.fromkeys(blocker for analysis in analyses
                                   for blocker in analysis.blockers))
    unknowns = tuple(dict.fromkeys(unknown for analysis in analyses
                                  for unknown in analysis.unknowns))
    next_checks = []
    for analysis in analyses:
        if analysis.completeness is AnalysisCompleteness.UNAVAILABLE:
            next_checks.append(
                f"Register a parser-backed {analysis.domain.value} metric artifact before diagnosis.")
    if timing_bad:
        next_checks.append("Inspect cited setup paths and delay composition; aggregate WNS alone is not a root cause.")
    if congestion_bad:
        next_checks.append("Inspect cited congestion regions and routing-layer demand/capacity.")
    if drc_bad:
        next_checks.append("Classify cited DRC markers by rule and physical location.")
    if "power_W" in fact_by_metric and "power_W" not in headroom:
        next_checks.append("Supply an evidence-backed power budget before claiming power headroom.")
    evidence = tuple(dict.fromkeys(pointer for analysis in analyses
                                   for pointer in analysis.evidence))
    report = DiagnosisReport(
        _id("diagnosis", (run_id, [item.analysis_id for item in analyses])),
        run_id, analyses, tuple(hypotheses), tuple(counter), blockers,
        unknowns, tuple(dict.fromkeys(next_checks)), evidence,
    )
    report.validate()
    return report


def diagnose_terminal_failure(
    runtime_view: Mapping[str, Any],
) -> tuple[DiagnosisReport, RuntimeFailureClass]:
    """Describe one terminal Runtime failure without inventing QoR facts.

    A failed run often has no protected QoR measurement. This path therefore
    preserves all four domains as unavailable, cites only the Runtime record
    and registered artifacts, and emits a coarse execution blocker. It does
    not parse arbitrary logs or assert a physical root cause.
    """
    run = runtime_view.get("run")
    if not isinstance(run, Mapping) or not isinstance(run.get("run_id"), str):
        raise ValueError("expected a Runtime describe view")
    run_id = run["run_id"]
    if run.get("status") not in {"failed", "cancelled", "timed_out", "lost"}:
        raise ValueError("terminal-failure diagnosis requires a failed Runtime run")
    attempts = [attempt for stage in runtime_view.get("stages", ())
                for attempt in stage.get("attempts", ())]
    terminal = [attempt for attempt in attempts if attempt.get("status") in {
        "failed", "cancelled", "timed_out", "lost",
    }]
    if not terminal:
        raise ValueError("Runtime failure view has no terminal failed attempt")
    attempt = terminal[-1]
    attempt_id = str(attempt.get("attempt_id") or "")
    if not attempt_id:
        raise ValueError("Runtime failure attempt lacks identity")
    failure = attempt.get("failure")
    failure = failure if isinstance(failure, Mapping) else {}
    category = str(failure.get("category") or run.get("status") or "unknown")
    plugin_id = str((run.get("task_spec") or {}).get("plugin_id") or "unknown")
    artifact_evidence = tuple(
        _pointer(artifact) for artifact in attempt.get("artifacts", ())
        if isinstance(artifact, Mapping)
        and isinstance(artifact.get("artifact_id"), str)
        and isinstance(artifact.get("sha256"), str)
    )
    run_evidence = EvidencePointer(f"run:{run_id}", _digest({
        "run_id": run_id, "status": run.get("status"),
        "attempt_id": attempt_id, "failure": dict(failure),
        "artifact_ids": [item.get("artifact_id")
                         for item in attempt.get("artifacts", ())],
    }))
    evidence = tuple(dict.fromkeys((run_evidence, *artifact_evidence)))
    unknown = (
        f"{plugin_id} ended as {run.get('status')} with Runtime category {category}; "
        "no protected QoR measurement is available.",
    )
    analyses = tuple(StageAnalysis(
        _id("analysis", (run_id, attempt_id, domain.value, category)),
        run_id, attempt_id, domain,
        "route" if domain in {AnalysisDomain.CONGESTION, AnalysisDomain.DRC}
        else "finish",
        AnalysisCompleteness.UNAVAILABLE, (), (), (), unknown, evidence,
        analyzer_id="deterministic-runtime-failure-v1",
    ) for domain in AnalysisDomain)
    failure_class = _runtime_failure_class(run.get("status"), category)
    report = DiagnosisReport(
        _id("diagnosis", (run_id, attempt_id, category)), run_id, analyses,
        (), (), ("backend_execution_failed",), unknown,
        (
            "Inspect the cited registered log and run-result artifacts before proposing a fix.",
            "Compare the failed RTL artifact with the last independently verified RTL checkpoint.",
        ), evidence, analyzer_id="deterministic-runtime-failure-v1",
    )
    report.validate()
    return report, failure_class


def _runtime_failure_class(status: Any, category: str) -> RuntimeFailureClass:
    if status == "timed_out" or category == "timeout":
        return RuntimeFailureClass.RESOURCE_LIMIT
    if status == "lost" or category in {
        "worker_lost", "lease_expired", "transient_infrastructure",
    }:
        return RuntimeFailureClass.TRANSIENT_INFRASTRUCTURE
    if category in {"rtl_verification_failed", "rtl_simulation_failed"}:
        return RuntimeFailureClass.DESIGN
    if category in {"invalid_configuration", "eda_configuration"}:
        return RuntimeFailureClass.EDA_CONFIGURATION
    return RuntimeFailureClass.UNKNOWN
