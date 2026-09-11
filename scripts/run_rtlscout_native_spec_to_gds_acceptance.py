#!/usr/bin/env python3
"""Run one real SpecIR -> native RTLScout -> verified RTL -> ORFS/GDS acceptance."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
for source_root in (ROOT, *(ROOT / "packages" / name / "src" for name in
                            ("contracts", "execution", "scheduler", "analysis"))):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from apps.api.app import ApiState  # noqa: E402
from openroad_platform_contracts import PortSpec, SpecIR  # noqa: E402


NATURAL_LANGUAGE_SPEC = (
    "设计一个名为 native_adder8 的无时钟组合逻辑模块。输入 a、b 均为 8 位无符号数，"
    "输出 sum 为低 8 位加法结果，也就是模 256 加法。要求所有 65536 组输入都正确，"
    "通过 lint、仿真和 mutation gate 后，用 Nangate45 完整实现到 GDS。"
)

REFERENCE_TESTBENCH = r"""module tb;
  integer ai;
  integer bi;
  integer total_checks;
  integer total_errors;
  logic [7:0] a;
  logic [7:0] b;
  logic [7:0] sum;
  logic [8:0] expected_wide;

  native_adder8 dut(.a(a), .b(b), .sum(sum));

  initial begin
    total_checks = 0;
    total_errors = 0;
    for (ai = 0; ai < 256; ai = ai + 1) begin
      for (bi = 0; bi < 256; bi = bi + 1) begin
        a = ai[7:0];
        b = bi[7:0];
        expected_wide = ai + bi;
        #1;
        total_checks = total_checks + 1;
        if (sum !== expected_wide[7:0]) begin
          total_errors = total_errors + 1;
          if (total_errors <= 8)
            $display("TB_ERROR a=%0d b=%0d expected=%0d actual=%0d", ai, bi, expected_wide[7:0], sum);
        end
      end
    end
    $display("TB_SUMMARY total=%0d errors=%0d", total_checks, total_errors);
    if (total_errors != 0) $fatal(1, "FAIL");
    $display("PASS");
    $finish;
  end
endmodule
"""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _source_snapshot(source: Path) -> dict[str, str]:
    def run(*argv: str) -> str:
        completed = subprocess.run(
            argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=60, check=False,
        )
        return completed.stdout.rstrip()
    return {
        "head": run("git", "-C", str(source), "rev-parse", "HEAD"),
        "status": run("git", "-C", str(source), "status", "--porcelain=v1"),
        "submodules": run("git", "-C", str(source), "submodule", "status", "--recursive"),
    }


def _run_and_collect(state: ApiState, receipt: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any]]:
    run_id = str(receipt["run"]["run"]["run_id"])
    completed = state.runtime.execute_once(
        run_id, on_line=lambda line: print(line, end="", flush=True)
    )
    collected = state.auto_collect_terminal_run(run_id)
    return completed.status.value, state.runtime.describe(run_id), collected


def _artifacts(view: dict[str, Any]) -> list[dict[str, Any]]:
    records = []
    for stage in view["stages"]:
        for attempt in stage["attempts"]:
            workspace = Path(attempt["workspace"])
            for artifact in attempt["artifacts"]:
                path = (workspace / artifact["store_key"]).resolve()
                if not path.is_file() or path.stat().st_size != artifact["size_bytes"]:
                    raise RuntimeError(f"registered artifact missing or changed size: {path}")
                digest = _sha256(path)
                if digest != artifact["sha256"]:
                    raise RuntimeError(f"registered artifact hash mismatch: {path}")
                records.append({
                    "kind": artifact["kind"], "path": str(path),
                    "sha256": digest, "size_bytes": path.stat().st_size,
                    "metadata": artifact.get("metadata") or {},
                })
    return records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--orfs-root", type=Path, default=ROOT.parent / "OpenROAD-flow-scripts")
    parser.add_argument("--max-steps", type=int, default=5)
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("refusing to overwrite non-empty RTLScout acceptance evidence")
    output.mkdir(parents=True, exist_ok=True)
    (output / "state").mkdir(parents=True, exist_ok=True)
    source = ROOT / ".external-src" / "rtlscout"
    source_before = _source_snapshot(source)

    state = ApiState(
        output / "api.db", output / "uploads", args.orfs_root,
        design_root=output / "designs", legacy_root=output / "legacy",
        yosys_bin=ROOT.parent / "bin" / "yosys",
        runtime_db_path=output / "state" / "runtime.sqlite",
        runtime_workspace_root=output / "work",
        load_taiwei_plugin=False,
    )
    spec = SpecIR(
        spec_id="specir-native-adder8-acceptance",
        design_id="native-adder8-acceptance",
        top="native_adder8",
        functionality="Combinational unsigned 8-bit addition modulo 256.",
        objective="Produce verified synthesizable RTL and a complete Nangate45 GDS baseline.",
        ports=(PortSpec("a", "input", 8), PortSpec("b", "input", 8),
               PortSpec("sum", "output", 8)),
        constraints={
            "platform": "nangate45", "target_stage": "finish",
            "clock_period_ns": 10.0, "core_utilization_pct": 10.0,
            "place_density": 0.45,
        },
        assumptions=("Combinational module with no clock or reset.", "Inputs are unsigned."),
        acceptance_criteria=(
            "sum equals (a + b) modulo 256 for all 65536 input pairs",
            "Runtime compile/lint and simulation gates pass",
            "Runtime mutation-quality evidence is retained",
            "ORFS finish emits a non-empty registered GDS artifact",
        ),
    )
    state.rtl_frontend.add_spec(spec)
    started = time.monotonic()

    rtl_receipt = state.submit_rtlscout_spec(spec.spec_id, {
        "testbench_source": REFERENCE_TESTBENCH,
        "testbench_top": "tb",
        "oracle_origin": "reference_model",
        "oracle_reviewed_by": "tutorial-acceptance/reference-exhaustive-adder-v1",
        "model": "codex-cli:gpt-5.6-terra",
        "max_steps": args.max_steps,
        "cost_metric": "transistors",
    })
    rtl_status, rtl_view, rtl_collection = _run_and_collect(state, rtl_receipt)
    if rtl_status != "succeeded":
        raise RuntimeError(f"native RTLScout failed: {rtl_status}")
    candidate_id = str(rtl_collection["candidate_id"])

    verify_status, verify_view, verify_collection = _run_and_collect(
        state, state.submit_rtl_verification(spec.spec_id, candidate_id=candidate_id)
    )
    sim_status, sim_view, sim_collection = _run_and_collect(
        state, state.submit_rtl_simulation(spec.spec_id, {}, candidate_id=candidate_id)
    )
    mutation_status, mutation_view, mutation_collection = _run_and_collect(
        state, state.submit_rtl_mutation_test(spec.spec_id, {
            "verifier_identity": "tutorial-acceptance/runtime-mutation-v1",
            "maximum_mutants": 32,
            "minimum_score": 0.80,
        }, candidate_id=candidate_id)
    )
    if verify_status != "succeeded" or sim_status != "succeeded":
        raise RuntimeError("verified RTL gates did not pass")

    orfs_receipt = state.promote_verified_rtl_to_orfs(spec.spec_id, candidate_id=candidate_id)
    orfs_status, orfs_view, orfs_collection = _run_and_collect(state, orfs_receipt)
    source_after = _source_snapshot(source)

    views = {
        "rtlscout": rtl_view, "compile_lint": verify_view,
        "simulation": sim_view, "mutation_quality": mutation_view,
        "orfs_finish": orfs_view,
    }
    artifacts = {name: _artifacts(view) for name, view in views.items()}
    rtl_kinds = {item["kind"] for item in artifacts["rtlscout"]}
    orfs_kinds = {item["kind"] for item in artifacts["orfs_finish"]}
    gds = next((item for item in artifacts["orfs_finish"] if item["kind"] == "gds"), None)
    protected = next((item for item in artifacts["orfs_finish"]
                      if Path(item["path"]).name == "common_evaluation.json"), None)
    provider_trace = next((item for item in artifacts["rtlscout"]
                           if item["kind"] == "model_trace"), None)
    native_trace = next((item for item in artifacts["rtlscout"]
                         if item["kind"] == "agent_trace"), None)
    native_receipt_artifact = next((item for item in artifacts["rtlscout"]
                                    if item["kind"] == "provenance"), None)
    native_receipt = (json.loads(Path(native_receipt_artifact["path"]).read_text(encoding="utf-8"))
                      if native_receipt_artifact else {})
    checks = {
        "native_rtlscout_runtime_succeeded": rtl_status == "succeeded",
        "native_entrypoint_provenance": (
            native_receipt.get("native_entrypoint") == "run_benchmark.py"
            and native_receipt.get("native_agent") == "core.agent.RTLAgent"
        ),
        "provider_trace_registered": provider_trace is not None,
        "native_chat_registered": native_trace is not None,
        "candidate_history_registered": "rtl_candidate_history" in rtl_kinds,
        "compile_lint_passed": verify_collection.get("status") == "passed",
        "simulation_passed": sim_collection.get("status") == "passed",
        "mutation_quality_passed": mutation_collection.get("status") == "passed",
        "orfs_finish_succeeded": orfs_status == "succeeded",
        "gds_registered_nonempty": gds is not None and gds["size_bytes"] > 0,
        "protected_evaluation_registered": protected is not None,
        "upstream_source_unchanged": source_before == source_after,
    }
    accepted = all(checks.values())
    summary = {
        "schema_version": 1,
        "kind": "rtlscout-native-spec-to-gds-acceptance",
        "accepted": accepted,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "natural_language_spec": NATURAL_LANGUAGE_SPEC,
        "natural_language_spec_sha256": _text_sha256(NATURAL_LANGUAGE_SPEC),
        "spec_ir": spec.to_dict(),
        "spec_ir_sha256": _text_sha256(json.dumps(spec.to_dict(), sort_keys=True)),
        "verification": {
            "testbench_sha256": _text_sha256(REFERENCE_TESTBENCH),
            "origin": "reference_model",
            "reviewed_by": "tutorial-acceptance/reference-exhaustive-adder-v1",
            "exhaustive_vectors": 65536,
        },
        "candidate_id": candidate_id,
        "statuses": {
            "rtlscout": rtl_status, "compile_lint": verify_status,
            "simulation": sim_status, "mutation_quality": mutation_status,
            "orfs_finish": orfs_status,
        },
        "collections": {
            "rtlscout": rtl_collection, "compile_lint": verify_collection,
            "simulation": sim_collection, "mutation_quality": mutation_collection,
            "orfs_finish": orfs_collection,
        },
        "runtime_views": views,
        "artifact_verification": artifacts,
        "checks": checks,
        "source_before": source_before,
        "source_after": source_after,
        "claim_boundary": (
            "One real bounded SpecIR-to-native-RTLScout-to-verified-RTL-to-GDS acceptance. "
            "It proves integration and evidence continuity for this specification; it is not "
            "a general RTL correctness or PPA-superiority claim."
        ),
    }
    summary_path = output / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output / "summary.sha256").write_text(
        f"{_sha256(summary_path)}  summary.json\n", encoding="utf-8"
    )
    print(json.dumps({
        "accepted": accepted, "summary": str(summary_path),
        "rtlscout_run_id": rtl_view["run"]["run_id"],
        "orfs_run_id": orfs_view["run"]["run_id"],
        "gds_sha256": gds["sha256"] if gds else None,
    }, ensure_ascii=False, indent=2))
    return 0 if accepted else 2


if __name__ == "__main__":
    raise SystemExit(main())
