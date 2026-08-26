#!/usr/bin/env python3
"""Summarize post-freeze RTL engineering reruns without rewriting the study."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _repair_rounds(report: dict) -> int:
    for trace in report.get("agent_traces") or []:
        if trace.get("agent_kind") != "verification-agent":
            continue
        for step in trace.get("steps") or []:
            metrics = step.get("metrics") or {}
            if isinstance(metrics.get("compiler_repair_rounds"), int):
                return metrics["compiler_repair_rounds"]
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frozen-analysis", type=Path, required=True)
    parser.add_argument("--ibex-rerun", type=Path, required=True)
    parser.add_argument("--uart-rerun", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    frozen = _load(args.frozen_analysis.expanduser().resolve())
    reruns = {
        "ibex_alu": _load(args.ibex_rerun.expanduser().resolve() / "report.json"),
        "uart_tx": _load(args.uart_rerun.expanduser().resolve() / "report.json"),
    }
    original = {row["design"]: row for row in frozen["attempt_rows"]
                if row["design"] in reruns and row["passed"] is False}
    if set(original) != set(reruns):
        raise RuntimeError("repair regression must map exactly to retained frozen failures")
    rows = []
    failure_labels = {
        "ibex_alu": "Spec Agent 将可保守默认的歧义误判为必须人工回答",
        "uart_tx": "Verification Agent 的 testbench 被 Verilator 拒绝且修订预算耗尽",
    }
    repair_labels = {
        "ibex_alu": "明确平台默认值和保留 opcode 的确定性 zero/no-op 自动消歧",
        "uart_tx": "把双编译器诊断反馈给独立 Verification Agent，最多追加三轮有界自修复",
    }
    for design in ("ibex_alu", "uart_tx"):
        report = reruns[design]
        rows.append({
            "design": design,
            "frozen_attempt": original[design]["attempt"],
            "frozen_status": "failed",
            "frozen_failure": failure_labels[design],
            "repair": repair_labels[design],
            "rerun_status": report.get("status"),
            "pipeline_status": (report.get("pipeline") or {}).get("status"),
            "compiler_repair_rounds": _repair_rounds(report),
            "rerun_spec_id": (report.get("specir") or {}).get("spec_id"),
            "rerun_failure": (report.get("failure") or {}).get("message"),
            "rerun_path": str((args.ibex_rerun if design == "ibex_alu" else args.uart_rerun)
                              .expanduser().resolve()),
        })
    result = {
        "schema_version": 1,
        "kind": "v2_rtl_post_freeze_engineering_regression",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if all(row["rerun_status"] == "passed" for row in rows) else "failed",
        "rows": rows,
        "frozen_result_unchanged": {
            "successes": frozen["successes"], "attempts": frozen["attempts"],
            "full_chain_pass_rate": frozen["full_chain_pass_rate"],
        },
        "claim_boundary": (
            "These are post-freeze engineering regressions for the two retained failures. "
            "They do not replace attempts, change the frozen 18/20 result, or enter paper statistics."
        ),
    }
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2),
                      encoding="utf-8")
    print(json.dumps({"output": str(output), "status": result["status"]}, ensure_ascii=False))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
