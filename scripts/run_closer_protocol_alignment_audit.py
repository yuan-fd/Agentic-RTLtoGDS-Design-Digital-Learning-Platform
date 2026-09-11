#!/usr/bin/env python3
"""Audit current evidence against public CLOSER-Bench paper requirements."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
for source_root in (ROOT, ROOT / "packages/contracts/src", ROOT / "packages/analysis/src"):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from openroad_platform_analysis import audit_closer_protocol_alignment  # noqa: E402


RTL = ROOT / "var/evidence/rtlscout-native-spec-to-gds-20260905-r8/summary.json"
RTL_SHA = "602a13dc56145ab3b3e3f7c290b92c269fe4f137b54e6e14b3185f8b075f4cb0"
RECOVERY = ROOT / "var/evidence/l1-typed-recovery-policy-20260905-r1/summary.json"
RECOVERY_SHA = "cfaeb05bff8c98356b4704d1a77849cc9fb3b83531cfd89e865a10fe4216781e"
EXECUTED_RECOVERY = ROOT / "var/evidence/platform-cross-stage-rtl-recovery-20260905-r2/summary.json"
EXECUTED_RECOVERY_SHA = "1606eb84083be453a9efe2e8b1cfa7986899089332d08059247f0250472bbf6d"
LOCK = ROOT / "integrations/closer_bench/source.lock.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("refusing to overwrite CLOSER alignment evidence")
    if (_sha256(RTL) != RTL_SHA or _sha256(RECOVERY) != RECOVERY_SHA
            or _sha256(EXECUTED_RECOVERY) != EXECUTED_RECOVERY_SHA):
        raise ValueError("canonical platform evidence drift")
    lock = json.loads(LOCK.read_text())
    if lock.get("execution_allowed") is not False or lock.get(
            "plugin_registration_allowed") is not False:
        raise ValueError("CLOSER source gate is not fail-closed")
    output.mkdir(parents=True, exist_ok=True)
    audit = audit_closer_protocol_alignment(
        json.loads(RTL.read_text()), json.loads(RECOVERY.read_text()),
        json.loads(EXECUTED_RECOVERY.read_text()))
    checks = {
        "paper_is_version_locked": lock["arxiv_id"] == "2607.16632v1"
            and lock["paper"]["pdf_sha256"] ==
            "84280d8b1a79924c5742fa1536fd1c48622cf93b7dd407d348b02c5b4750ac28",
        "missing_source_blocks_execution": lock["execution_allowed"] is False
            and lock["plugin_registration_allowed"] is False,
        "real_spec_to_gds_is_counted": any(
            item["criterion"] == "one_real_spec_to_gds_path"
            and item["status"] == "met" for item in audit["criteria"]),
        "typed_recovery_is_counted": any(
            item["criterion"] == "typed_cross_stage_recovery_policy"
            and item["status"] == "met" for item in audit["criteria"]),
        "executed_recovery_is_counted_without_official_claim": any(
            item["criterion"] == "executed_cross_stage_recovery_and_rollback_precision"
            and item["status"] == "met" for item in audit["criteria"]),
        "no_official_claim": audit["official_closer_bench_result"] is False
            and audit["ready_for_official_benchmark_claim"] is False,
        "source_evidence_pinned": _sha256(RTL) == RTL_SHA
            and _sha256(RECOVERY) == RECOVERY_SHA
            and _sha256(EXECUTED_RECOVERY) == EXECUTED_RECOVERY_SHA,
    }
    summary = {
        "schema_version": 1,
        "kind": "closer-paper-protocol-alignment-acceptance",
        "accepted": all(checks.values()),
        "closer_source_lock": {"path": str(LOCK.relative_to(ROOT)),
                               "sha256": _sha256(LOCK)},
        "inputs": [
            {"path": str(RTL.relative_to(ROOT)), "sha256": RTL_SHA},
            {"path": str(RECOVERY.relative_to(ROOT)), "sha256": RECOVERY_SHA},
            {"path": str(EXECUTED_RECOVERY.relative_to(ROOT)),
             "sha256": EXECUTED_RECOVERY_SHA},
        ],
        "audit": audit,
        "checks": checks,
        "claim_boundary": (
            "Evidence-backed alignment audit against the public CLOSER-Bench paper "
            "only. No CLOSER source, task, hidden oracle or scorer was available or "
            "executed, so this is not a benchmark result. One separately frozen "
            "platform-owned fault now supplies bounded executed recovery evidence; "
            "the official stage-paired tasks, hidden oracle and repeated trials "
            "remain unavailable."),
    }
    path = output / "summary.json"
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    digest = _sha256(path)
    (output / "summary.sha256").write_text(f"{digest}  summary.json\n")
    print(json.dumps({"accepted": summary["accepted"], "summary": str(path),
                      "sha256": digest, "counts": audit["counts"]}, indent=2))
    return 0 if summary["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
