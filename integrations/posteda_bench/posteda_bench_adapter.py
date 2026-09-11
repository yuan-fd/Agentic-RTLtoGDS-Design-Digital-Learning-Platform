#!/usr/bin/env python3
"""Bounded PostEDA-Bench public-case loader and hidden-label scorer."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


PLUGIN_ID = "posteda-bench"
BENCHMARK_ID = "posteda-bench-51884e5"
COMMIT = "51884e5f20e6e199219cec87c1c779a3dfab95bc"
TREE = "c5ccdf6e7165bcc9749e10dacd023bfe5cde20a4"
LICENSE_SHA256 = "ef11c38a4df050ec831b0186a6d73fe72e2dadcfe0ea7563394596b8e75a1526"
ADMITTED_TASKS = {"drc_essential/L1/q1"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()).hexdigest()


def _write(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(
        value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    temporary.replace(path)


def _source() -> tuple[Path, dict[str, Any]]:
    source = Path(os.environ["POSTEDA_BENCH_SOURCE"]).expanduser().resolve()
    lock = Path(os.environ["POSTEDA_BENCH_SOURCE_LOCK"]).expanduser().resolve()
    if _sha256(lock) != os.environ["POSTEDA_BENCH_SOURCE_LOCK_SHA256"]:
        raise ValueError("PostEDA-Bench source lock drift")
    locked = json.loads(lock.read_text())
    git = ("git", "-C", str(source))
    commit = subprocess.check_output((*git, "rev-parse", "HEAD"), text=True).strip()
    tree = subprocess.check_output((*git, "rev-parse", "HEAD^{tree}"), text=True).strip()
    dirty = subprocess.check_output(
        (*git, "status", "--porcelain", "--untracked-files=all"), text=True)
    attached = subprocess.run(
        (*git, "symbolic-ref", "-q", "HEAD"), stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, check=False).returncode == 0
    if (commit != COMMIT or tree != TREE or dirty or attached
            or locked.get("required_commit") != COMMIT
            or locked.get("required_tree") != TREE
            or _sha256(source / "LICENSE") != LICENSE_SHA256):
        raise ValueError("PostEDA-Bench checkout identity or license drift")
    for relative, expected in locked["locked_files"].items():
        if _sha256(source / relative) != expected:
            raise ValueError(f"PostEDA-Bench locked file drift: {relative}")
    return source, {"repository": locked["canonical_upstream"],
                    "commit": commit, "tree": tree,
                    "license": "CC-BY-4.0", "license_sha256": LICENSE_SHA256}


def _task(request: Mapping[str, Any]) -> tuple[str, str, Mapping[str, Any] | None]:
    if request.get("schema_version") != 1 or (request.get("plugin") or {}).get(
            "plugin_id") != PLUGIN_ID:
        raise ValueError("invalid PostEDA adapter envelope")
    task = request.get("task")
    if not isinstance(task, Mapping) or task.get("plugin_id") != PLUGIN_ID:
        raise ValueError("task does not target PostEDA-Bench")
    inputs, parameters = task.get("inputs"), task.get("parameters")
    if not isinstance(inputs, Mapping) or not isinstance(parameters, Mapping):
        raise ValueError("PostEDA inputs and parameters must be objects")
    mode = inputs.get("mode")
    expected_inputs = ({"mode", "benchmark_id", "task_id"} if mode == "public_case"
                       else {"mode", "benchmark_id", "task_id", "prediction"})
    expected_params = ({"parser"} if mode == "public_case" else {"score_protocol"})
    if set(inputs) != expected_inputs or set(parameters) != expected_params:
        raise ValueError("PostEDA task contains an unapproved field")
    if inputs.get("benchmark_id") != BENCHMARK_ID or inputs.get("task_id") not in ADMITTED_TASKS:
        raise ValueError("PostEDA benchmark/task is outside the admission")
    if mode == "public_case" and parameters.get("parser") != "upstream-klayout-report":
        raise ValueError("unsupported PostEDA public parser")
    if mode == "evaluate_diagnosis" and parameters.get(
            "score_protocol") != "derived-diagnostic-v1":
        raise ValueError("unsupported PostEDA score protocol")
    if mode not in {"public_case", "evaluate_diagnosis"}:
        raise ValueError("unsupported PostEDA adapter mode")
    return mode, str(inputs["task_id"]), inputs.get("prediction")


def _parse_native(stdout: str) -> tuple[str, str, dict[str, int]]:
    description = re.search(r"^Description:\s*(.+)$", stdout, re.MULTILINE)
    top = re.search(r"^Top Cell:\s*(.+)$", stdout, re.MULTILINE)
    headers = list(re.finditer(
        r"^---\s+([^|]+?)\s+\|\s+cell:\s+(.+?)\s+---$", stdout, re.MULTILINE))
    counts: dict[str, int] = {}
    for index, match in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(stdout)
        block = stdout[match.end():end]
        visible = len(re.findall(r"^\[\d+\]\s+\{", block, re.MULTILINE))
        omitted = re.search(r"(\d+) more not displayed", block)
        category = match.group(1).strip()
        counts[category] = counts.get(category, 0) + visible + (
            int(omitted.group(1)) if omitted else 0)
    if not description or not top or not counts:
        raise ValueError("native PostEDA public report output is incomplete")
    return description.group(1).strip(), top.group(1).strip(), counts


def _public_case(source: Path, workspace: Path, task_id: str) -> tuple[dict, dict]:
    task = source / "benchmark/drc_bench" / task_id
    native = workspace / "native"
    native.mkdir()
    for name in ("drc_error_collection.py", "6_drc_count.rpt"):
        shutil.copy2(task / name, native / name)
    if (native / "info.json").exists():
        raise PermissionError("hidden benchmark labels crossed the public-case firewall")
    klayout = Path(os.environ["POSTEDA_BENCH_KLAYOUT"]).expanduser().resolve()
    command = [str(klayout), "-b", "-r", "drc_error_collection.py"]
    result = subprocess.run(command, cwd=native, text=True, capture_output=True,
                            timeout=120, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"native KLayout parser failed: {result.stderr[-1000:]}")
    description, top, counts = _parse_native(result.stdout)
    case = {
        "schema_version": 1, "kind": "posteda_public_drc_case",
        "task_id": task_id, "prompt": (task / "prompt.txt").read_text(),
        "description": description, "top_cell": top,
        "error_type_counts": counts, "total_errors": sum(counts.values()),
        "report_sha256": _sha256(task / "6_drc_count.rpt"),
        "native_entrypoint": "drc_error_collection.py via klayout -b -r",
        "hidden_labels_included": False,
    }
    trace = {"schema_version": 1, "task_id": task_id,
             "argv": ["klayout", "-b", "-r", "drc_error_collection.py"],
             "exit_code": result.returncode,
             "stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(),
             "hidden_label_firewall": "info.json absent from native workspace",
             "network": "not requested", "source_mutation": False}
    return case, trace


def _prediction(value: Any, task_id: str) -> dict[str, Any]:
    required = {"schema_version", "prediction_id", "task_id", "error_type_counts",
                "total_errors", "decision", "rationale", "evidence",
                "hidden_label_accessed"}
    if (not isinstance(value, Mapping) or set(value) != required
            or value.get("schema_version") != 1 or value.get("task_id") != task_id
            or value.get("hidden_label_accessed") is not False):
        raise ValueError("PostEDA prediction is malformed or label-tainted")
    counts, total = value.get("error_type_counts"), value.get("total_errors")
    if (not isinstance(counts, Mapping)
            or not all(isinstance(key, str) and not isinstance(count, bool)
                       and isinstance(count, int) and count >= 0
                       for key, count in counts.items())
            or isinstance(total, bool) or not isinstance(total, int)
            or total != sum(counts.values())):
        raise ValueError("PostEDA prediction counts are invalid")
    if value.get("decision") not in {
            "inspect_drc_geometry", "propose_bounded_repair", "abstain"}:
        raise ValueError("PostEDA prediction decision is untyped")
    evidence = value.get("evidence")
    if (not isinstance(evidence, list) or not evidence
            or not all(isinstance(item, Mapping)
                       and set(item) == {"schema_version", "ref", "sha256"}
                       and item.get("schema_version") == 1
                       and isinstance(item.get("ref"), str)
                       and item["ref"].startswith("artifact:runtime-")
                       and isinstance(item.get("sha256"), str)
                       and re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
                       for item in evidence)):
        raise ValueError("PostEDA prediction lacks Runtime artifact evidence")
    return dict(value)


def _score(source: Path, task_id: str, raw: Any) -> tuple[dict, dict]:
    prediction = _prediction(raw, task_id)
    hidden_path = source / "benchmark/drc_bench" / task_id / "info.json"
    hidden_bytes = hidden_path.read_bytes()
    hidden = json.loads(hidden_bytes)
    expected_counts = hidden.get("init_error_types")
    expected_total = hidden.get("init_errors_num")
    exact_counts = prediction["error_type_counts"] == expected_counts
    exact_total = prediction["total_errors"] == expected_total
    evidence_grounded = bool(prediction["evidence"])
    decision_grounded = prediction["decision"] == (
        "inspect_drc_geometry" if expected_total else "abstain")
    components = (exact_counts, exact_total, evidence_grounded, decision_grounded)
    score = {
        "schema_version": 1,
        "evaluation_id": f"posteda-eval-{_digest((task_id, prediction['prediction_id']))[:20]}",
        "task_id": task_id, "prediction_id": prediction["prediction_id"],
        "exact_type_counts": exact_counts, "exact_total_errors": exact_total,
        "evidence_grounded": evidence_grounded,
        "decision_grounded": decision_grounded,
        "diagnostic_score": sum(components) / 4,
        "official_metric": False,
        "notes": [
            "Derived platform diagnostic score; not PostEDA-Bench SR, ERR, or VRR.",
            "The safe decision component checks inspect-before-repair, not repair quality.",
        ],
        "evidence": prediction["evidence"],
    }
    trace = {
        "schema_version": 1, "task_id": task_id,
        "prediction_sha256": _digest(prediction),
        "hidden_label_sha256": hashlib.sha256(hidden_bytes).hexdigest(),
        "hidden_label_opened_after_prediction": True,
        "hidden_label_values_exported": False,
        "official_metric": False,
    }
    return score, trace


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    started = _now()
    workspace = args.result.resolve().parent
    try:
        request = json.loads(args.request.read_text())
        mode, task_id, prediction = _task(request)
        source, identity = _source()
        if mode == "public_case":
            case, trace = _public_case(source, workspace, task_id)
            _write(workspace / "public_case.json", case)
            _write(workspace / "native_trace.json", {**trace, "upstream": identity})
            artifacts = [
                {"kind": "benchmark_public_case", "path": "public_case.json"},
                {"kind": "benchmark_native_trace", "path": "native_trace.json"},
            ]
        else:
            score, trace = _score(source, task_id, prediction)
            _write(workspace / "diagnosis_score.json", score)
            _write(workspace / "evaluation_trace.json", {**trace, "upstream": identity})
            artifacts = [
                {"kind": "benchmark_diagnosis_score", "path": "diagnosis_score.json"},
                {"kind": "benchmark_evaluation_trace", "path": "evaluation_trace.json"},
            ]
        _write(args.result, {
            "schema_version": 1, "status": "succeeded", "exit_code": 0,
            "started_at": started, "ended_at": _now(), "metrics": [],
            "artifacts": artifacts, "failure": None,
            "provenance": {"upstream_commit": COMMIT, "mode": mode,
                           "official_metric": False},
        })
        print(json.dumps({"event": f"posteda.{mode}.completed", "task_id": task_id}))
        return 0
    except Exception as exc:
        failure = {"category": "posteda_bench_error",
                   "message": f"{type(exc).__name__}: {exc}"}
        _write(args.result, {
            "schema_version": 1, "status": "failed", "exit_code": 1,
            "started_at": started, "ended_at": _now(), "metrics": [],
            "artifacts": [], "failure": failure,
            "provenance": {"upstream_commit": COMMIT},
        })
        print(json.dumps({"event": "posteda.failed", **failure}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
