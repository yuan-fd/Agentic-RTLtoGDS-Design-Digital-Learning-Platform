"""Adapt a public PostEDA DRC case into the deterministic diagnosis contract."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from openroad_platform_contracts import (
    AnalysisTarget, DiagnosticDecision, DiagnosisReport, EvidencePointer,
    PostEDADiagnosisPrediction,
)

from .stage_diagnostics import diagnose_runtime


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()).hexdigest()


def diagnose_posteda_public_case(
    public_case: Mapping[str, Any], *, run_id: str, attempt_id: str,
    artifact_id: str, artifact_sha256: str, target_evidence: EvidencePointer,
) -> tuple[DiagnosisReport, PostEDADiagnosisPrediction]:
    """Diagnose public artifacts only; hidden benchmark labels are not accepted."""
    required = {
        "schema_version", "kind", "task_id", "prompt", "description",
        "top_cell", "error_type_counts", "total_errors", "report_sha256",
        "native_entrypoint", "hidden_labels_included",
    }
    if set(public_case) != required or public_case.get("schema_version") != 1 \
            or public_case.get("kind") != "posteda_public_drc_case" \
            or public_case.get("hidden_labels_included") is not False:
        raise ValueError("PostEDA public case envelope is malformed")
    if public_case.get("report_sha256") != artifact_sha256:
        # The registered artifact is public_case.json, not the nested report;
        # bind it independently below and require the report digest to be valid.
        report_sha = public_case.get("report_sha256")
        if (not isinstance(report_sha, str) or len(report_sha) != 64
                or any(ch not in "0123456789abcdef" for ch in report_sha)):
            raise ValueError("PostEDA public report digest is invalid")
    counts = public_case.get("error_type_counts")
    total = public_case.get("total_errors")
    if (not isinstance(counts, Mapping)
            or not all(isinstance(key, str) and not isinstance(value, bool)
                       and isinstance(value, int) and value >= 0
                       for key, value in counts.items())
            or isinstance(total, bool) or not isinstance(total, int)
            or total != sum(counts.values())):
        raise ValueError("PostEDA public case counts are invalid")
    pointer = EvidencePointer(f"artifact:runtime-{artifact_id}", artifact_sha256)
    target_evidence.validate()
    runtime_view = {
        "run": {"run_id": run_id, "status": "succeeded"},
        "stages": [{"attempts": [{
            "attempt_id": attempt_id, "status": "succeeded",
            "artifacts": [{"artifact_id": artifact_id, "sha256": artifact_sha256,
                           "kind": "benchmark_public_case", "metadata": {}}],
            "metrics": [{"name": "drc_errors", "value": total, "unit": "count",
                         "parser_id": "posteda-native-klayout-v1",
                         "parser_version": "51884e5f",
                         "source_artifact_id": artifact_id}],
        }]}],
    }
    report = diagnose_runtime(runtime_view, targets=(
        AnalysisTarget("drc_errors", "==", 0.0, "count", (target_evidence,)),
    ))
    decision = (DiagnosticDecision.INSPECT_DRC_GEOMETRY if total
                else DiagnosticDecision.ABSTAIN)
    types = ", ".join(sorted(counts)) if counts else "none"
    prediction = PostEDADiagnosisPrediction(
        prediction_id=f"posteda-prediction-{_digest((public_case['task_id'], counts))[:20]}",
        task_id=str(public_case["task_id"]),
        error_type_counts={str(key): int(value) for key, value in counts.items()},
        total_errors=total, decision=decision,
        rationale=(
            f"The cited public KLayout report contains {total} marker(s) across "
            f"types {types}. Inspect the cited marker geometry before proposing a repair."
            if total else "The cited public report contains no marker; abstain from repair."),
        evidence=(pointer,), hidden_label_accessed=False,
    )
    prediction.validate()
    return report, prediction
