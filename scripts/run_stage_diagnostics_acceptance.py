#!/usr/bin/env python3
"""Run four deterministic analyzers over a real accepted Runtime view."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
for source_root in (ROOT, *(ROOT / "packages" / name / "src" for name in
                            ("contracts", "analysis"))):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from openroad_platform_analysis import diagnose_runtime  # noqa: E402
from openroad_platform_contracts import AnalysisTarget, EvidencePointer  # noqa: E402


DEFAULT_INPUT = ROOT / "var/evidence/rtlscout-native-spec-to-gds-20260905-r8/summary.json"
EXPECTED_INPUT_SHA256 = "602a13dc56145ab3b3e3f7c290b92c269fe4f137b54e6e14b3185f8b075f4cb0"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    source = args.input.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("refusing to overwrite stage-diagnostics evidence")
    if _sha256(source) != EXPECTED_INPUT_SHA256:
        raise ValueError("canonical RTLScout-to-GDS acceptance evidence drift")
    output.mkdir(parents=True, exist_ok=True)
    accepted = json.loads(source.read_text())
    if accepted.get("accepted") is not True:
        raise ValueError("input unified acceptance did not pass")
    evaluator_source = ROOT / "packages/analysis/src/openroad_platform_analysis/common_evaluator.py"
    policy = (EvidencePointer("source:protected-orfs-evaluator-v3",
                              _sha256(evaluator_source)),)
    runtime_view = accepted["runtime_views"]["orfs_finish"]
    report = diagnose_runtime(runtime_view, targets=(
        AnalysisTarget("setup_wns_ns", ">=", 0.0, "ns", policy),
        AnalysisTarget("hold_wns_ns", ">=", 0.0, "ns", policy),
        AnalysisTarget("drc_errors", "==", 0.0, "count", policy),
        AnalysisTarget("congestion_overflow", "<=", 0.0, "count", policy),
    ))
    by_domain = {item.domain.value: item for item in report.analyses}
    facts = {fact.metric: fact for item in report.analyses for fact in item.facts}
    headroom = {item.metric: item for analysis in report.analyses
                for item in analysis.headroom}
    registered_refs = {
        f"artifact:runtime-{artifact['artifact_id']}"
        for stage in runtime_view.get("stages", ())
        for attempt in stage.get("attempts", ())
        for artifact in attempt.get("artifacts", ())
    }
    checks = {
        "four_domains": set(by_domain) == {"timing", "congestion", "drc", "power"},
        "timing_is_protected_fact": facts["setup_wns_ns"].authority == "protected_evaluator",
        "timing_value_preserved": facts["setup_wns_ns"].value == 5.65128,
        "timing_headroom_computed": headroom["setup_wns_ns"].margin == 5.65128 and
            headroom["setup_wns_ns"].status == "satisfied",
        "drc_value_preserved": facts["drc_errors"].value == 0 and
            headroom["drc_errors"].status == "satisfied",
        "power_fact_without_fake_budget": facts["power_W"].value == 8.214e-06 and
            not by_domain["power"].headroom and
            any("headroom is unknown" in item for item in by_domain["power"].unknowns),
        "missing_congestion_is_explicit": by_domain["congestion"].completeness.value == "unavailable" and
            not by_domain["congestion"].facts and not by_domain["congestion"].headroom,
        "all_metric_evidence_registered": all(
            pointer.ref in registered_refs
            for fact in facts.values() for pointer in fact.evidence),
        "no_unverified_root_cause": not report.hypotheses,
        "no_blocker_on_feasible_observed_domains": not report.blockers,
        "input_acceptance_pinned": _sha256(source) == EXPECTED_INPUT_SHA256,
    }
    summary = {
        "schema_version": 1,
        "kind": "four-domain-stage-diagnostics-acceptance",
        "accepted": all(checks.values()),
        "input_evidence": {"source_document": str(source.relative_to(ROOT)),
                           "sha256": _sha256(source)},
        "protected_rule_source": {"source_document": str(evaluator_source.relative_to(ROOT)),
                                  "sha256": _sha256(evaluator_source)},
        "diagnosis_report": report.to_dict(),
        "checks": checks,
        "claim_boundary": (
            "Deterministic normalization and threshold analysis over one real accepted "
            "Runtime view. Missing congestion remains unavailable and absent power budget "
            "remains unknown. This does not claim root-cause localization."
        ),
    }
    summary_path = output / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    digest = _sha256(summary_path)
    (output / "summary.sha256").write_text(f"{digest}  summary.json\n")
    print(json.dumps({"accepted": summary["accepted"], "summary": str(summary_path),
                      "sha256": digest}, indent=2))
    return 0 if summary["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
