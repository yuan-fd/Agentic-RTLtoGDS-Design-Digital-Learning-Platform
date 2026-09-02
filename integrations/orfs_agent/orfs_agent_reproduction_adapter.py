#!/usr/bin/env python3
"""Execute one unmodified ORFS-Agent paper-style candidate in Runtime isolation.

This is deliberately an *execution* adapter, not a local optimiser.  Candidate
selection remains the pinned upstream ORFS-Agent analyst + scikit-optimize
GP/EI implementation.  The adapter implements the boundary used by upstream
``run_or_job.sh``: a 12-field candidate becomes its original environment
variables and an isolated ``make tunereport`` invocation.

The original launcher assumes a shared ORFS checkout, hard-coded SSH hosts and
one mutable results tree.  Runtime cannot use that safely.  Here each attempt
gets a private copy of the pinned paper flow and private AutoTuner configs;
neither upstream checkout is modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


PARAMETERS = (
    "CLK", "UTIL", "TNS_End_Percent", "GP_PAD", "DP_PAD", "DPO",
    "PIN_ADJ", "UP_ADJ", "LB_ADDON", "HIER_SYNTH", "CTS_CSIZE", "CTS_CDIA",
)
SUPPORTED_PLATFORMS = {"asap7", "sky130hd"}
SUPPORTED_DESIGNS = {"aes", "ibex", "jpeg"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _required_path(variable: str) -> Path:
    raw = os.environ.get(variable)
    if not raw:
        raise ValueError(f"{variable} is required in the admitted plugin environment")
    path = Path(raw).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"{variable} does not exist: {path}")
    return path


def _check_clean_git(root: Path, expected_commit: str, label: str) -> dict[str, str]:
    actual = subprocess.check_output(("git", "-C", str(root), "rev-parse", "HEAD"), text=True).strip()
    if actual != expected_commit:
        raise ValueError(f"{label} commit mismatch: {actual} != {expected_commit}")
    if subprocess.run(("git", "-C", str(root), "symbolic-ref", "-q", "HEAD"),
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        raise ValueError(f"{label} source must be detached")
    status = subprocess.check_output(
        ("git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"), text=True
    ).strip()
    if status:
        raise ValueError(f"{label} source tree is not clean")
    return {"path": str(root), "commit": actual}


def _number(candidate: Mapping[str, Any], name: str, *, integer: bool = False) -> int | float:
    value = candidate.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"candidate {name} must be numeric")
    numeric = int(value) if integer else float(value)
    if integer and float(value) != numeric:
        raise ValueError(f"candidate {name} must be an integer")
    return numeric


def validate_candidate(candidate: Mapping[str, Any], *, platform: str) -> dict[str, int | float]:
    """Validate only the upstream published 12-dimensional domain.

    No platform-only feasibility projection is applied.  In particular, this
    reproduction protocol intentionally permits candidate-specific clock and
    does not inject the historical ``DP_PAD <= GP_PAD`` restriction.
    """
    if set(candidate) != set(PARAMETERS):
        missing = sorted(set(PARAMETERS) - set(candidate))
        extra = sorted(set(candidate) - set(PARAMETERS))
        raise ValueError(f"candidate must contain exactly the upstream 12 fields; missing={missing}, extra={extra}")
    clk_low, clk_high = ((100.0, 10000.0) if platform == "asap7" else (0.5, 15.0))
    value = {
        "CLK": _number(candidate, "CLK"),
        "UTIL": _number(candidate, "UTIL", integer=True),
        "TNS_End_Percent": _number(candidate, "TNS_End_Percent", integer=True),
        "GP_PAD": _number(candidate, "GP_PAD", integer=True),
        "DP_PAD": _number(candidate, "DP_PAD", integer=True),
        "DPO": _number(candidate, "DPO", integer=True),
        "PIN_ADJ": _number(candidate, "PIN_ADJ"),
        "UP_ADJ": _number(candidate, "UP_ADJ"),
        "LB_ADDON": _number(candidate, "LB_ADDON"),
        "HIER_SYNTH": _number(candidate, "HIER_SYNTH", integer=True),
        "CTS_CSIZE": _number(candidate, "CTS_CSIZE", integer=True),
        "CTS_CDIA": _number(candidate, "CTS_CDIA", integer=True),
    }
    bounds = {
        "CLK": (clk_low, clk_high), "UTIL": (20, 69), "TNS_End_Percent": (0, 100),
        "GP_PAD": (0, 3), "DP_PAD": (0, 3), "DPO": (0, 1),
        "PIN_ADJ": (0.1, 0.7), "UP_ADJ": (0.1, 0.7), "LB_ADDON": (0.0, 0.99),
        "HIER_SYNTH": (0, 1), "CTS_CSIZE": (10, 40), "CTS_CDIA": (80, 120),
    }
    for name, (lower, upper) in bounds.items():
        if not lower <= value[name] <= upper:
            raise ValueError(f"candidate {name}={value[name]!r} is outside upstream range [{lower}, {upper}]")
    return value


def _materialize(root: Path, *, source: Path, paper_orfs: Path,
                 platform: str, design: str, candidate: Mapping[str, int | float]) -> dict[str, Any]:
    """Create the exact upstream run_or_job input shape within one attempt."""
    flow_source = paper_orfs / "flow"
    private_source = source / "AutoTuner-integration" / "AutoTuner" / "autotune_configs"
    if not flow_source.is_dir() or not private_source.is_dir():
        raise FileNotFoundError("pinned paper flow or ORFS-Agent AutoTuner configs are absent")
    flow = root / "orfs-flow"
    private = root / "autotune-configs"
    # root is Runtime-created and guaranteed empty for a fresh attempt.
    shutil.copytree(flow_source, flow, symlinks=True)
    shutil.copytree(private_source, private, symlinks=True)
    config = private / f"{design}_{platform}.mk"
    sdc = private / ({"aes": "aes_cipher_top.sdc", "ibex": "ibex_core.sdc", "jpeg": "jpeg_encoder.sdc"}[design])
    route = private / f"fastroute_{platform}.tcl"
    for path in (config, sdc, route):
        if not path.is_file():
            raise FileNotFoundError(f"upstream material required for candidate is absent: {path}")
    work_home = root / "work"
    variant = "orfs_agent_candidate"
    # This mapping is a direct transcription of upstream run_or_job.sh.  The
    # values deliberately remain environment variables (rather than a new
    # generated optimizer config) so ORFS evaluates exactly its native knobs.
    environment = {
        "CLK_PERIOD": str(candidate["CLK"]),
        "ABC_CLOCK_PERIOD_IN_PS": str(candidate["CLK"]),
        "CORE_UTILIZATION": str(candidate["UTIL"]),
        "CORE_ASPECT_RATIO": "1",
        "PLACE_DENSITY_LB_ADDON": str(candidate["LB_ADDON"]),
        "TNS_END_PERCENT": str(candidate["TNS_End_Percent"]),
        "RECOVER_POWER": "0",
        "SYNTH_HIERARCHICAL": str(candidate["HIER_SYNTH"]),
        "CELL_PAD_IN_SITES_GLOBAL_PLACEMENT": str(candidate["GP_PAD"]),
        "CELL_PAD_IN_SITES_DETAIL_PLACEMENT": str(candidate["DP_PAD"]),
        "ENABLE_DPO": str(candidate["DPO"]),
        "GPL_TIMING_DRIVEN": "1",
        "GPL_ROUTABILITY_DRIVEN": "1",
        "CTS_CLUSTER_SIZE": str(candidate["CTS_CSIZE"]),
        "CTS_CLUSTER_DIAMETER": str(candidate["CTS_CDIA"]),
        "PIN_LAYER_ADJUST": str(candidate["PIN_ADJ"]),
        "UP_LAYER_ADJUST": str(candidate["UP_ADJ"]),
        "FASTROUTE_TCL": str(route),
        "RUN_DIR": str(private),
        "WORK_HOME": str(work_home),
        "FLOW_VARIANT": variant,
    }
    receipt = {
        "schema_version": 1,
        "kind": "orfs-agent-paper-candidate-materialization",
        "platform": platform,
        "design": design,
        "candidate": dict(candidate),
        "upstream_wrapper": "AutoTuner-integration/ORFS-with-AutoTuner/run_or_job.sh",
        "native_environment_mapping": environment,
        "flow": str(flow),
        "private_config": str(config),
        "private_sdc": str(sdc),
        "private_fastroute": str(route),
        "expected_report_directory": str(work_home / "reports" / platform / design / variant),
    }
    _write(root / "candidate_materialization.json", receipt)
    return receipt


def _copy_report(root: Path, materialization: Mapping[str, Any]) -> dict[str, Any]:
    reports = Path(str(materialization["expected_report_directory"]))
    final = reports / "6_report.json"
    cts = reports / "4_1_cts.json"
    if not final.is_file() or final.stat().st_size == 0:
        raise FileNotFoundError(f"ORFS did not emit final report: {final}")
    final_metrics = json.loads(final.read_text(encoding="utf-8"))
    cts_metrics = (json.loads(cts.read_text(encoding="utf-8")) if cts.is_file() else {})
    candidate = materialization["candidate"]
    metrics = {
        "schema_version": 1,
        "raw_final_report": final_metrics,
        "raw_cts_report": cts_metrics,
        "ECP_final": float(candidate["CLK"]) - float(final_metrics["finish__timing__setup__ws"]),
        "ECP_cts": (float(candidate["CLK"]) - float(cts_metrics["cts__timing__setup__ws"])
                    if "cts__timing__setup__ws" in cts_metrics else None),
        "candidate_clock_units": "ps" if materialization["platform"] == "asap7" else "ns",
    }
    _write(root / "candidate_metrics.json", metrics)
    return metrics


def _result(*, status: str, code: int, started: str, artifacts: list[dict[str, str]],
            provenance: Mapping[str, Any], failure: Mapping[str, str] | None = None) -> dict[str, Any]:
    return {"schema_version": 1, "status": status, "exit_code": code,
            "started_at": started, "ended_at": _now(), "metrics": [],
            "artifacts": artifacts, "failure": failure, "provenance": dict(provenance)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    started = _now()
    try:
        request = json.loads(args.request.read_text(encoding="utf-8"))
        task = request["task"]
        if request.get("plugin", {}).get("plugin_id") != "orfs-agent-paper-reproduction":
            raise ValueError("request is not for orfs-agent-paper-reproduction")
        inputs = task.get("inputs")
        if not isinstance(inputs, Mapping):
            raise ValueError("task inputs must be an object")
        platform, design = str(inputs.get("platform", "")), str(inputs.get("design", ""))
        if platform not in SUPPORTED_PLATFORMS or design not in SUPPORTED_DESIGNS:
            raise ValueError("paper reproduction supports {aes,ibex,jpeg} on {asap7,sky130hd}")
        raw_candidate = inputs.get("candidate")
        if not isinstance(raw_candidate, Mapping):
            raise ValueError("task inputs require a 12-field candidate object")
        candidate = validate_candidate(raw_candidate, platform=platform)
        source = _required_path("ORFS_AGENT_SOURCE")
        paper_orfs = _required_path("ORFS_AGENT_PAPER_ORFS_ROOT")
        openroad = _required_path("OPENROAD_BIN")
        yosys = _required_path("YOSYS_BIN")
        source_receipt = _check_clean_git(source, os.environ["ORFS_AGENT_EXPECTED_COMMIT"], "ORFS-Agent")
        flow_receipt = _check_clean_git(paper_orfs, os.environ["ORFS_AGENT_PAPER_ORFS_COMMIT"], "paper ORFS")
        root = args.result.parent.resolve()
        materialization = _materialize(root, source=source, paper_orfs=paper_orfs,
                                       platform=platform, design=design, candidate=candidate)
        environment = dict(os.environ)
        environment.update(materialization["native_environment_mapping"])
        environment["OPENROAD_EXE"] = str(openroad)
        environment["YOSYS_EXE"] = str(yosys)
        environment["PATH"] = os.pathsep.join((str(openroad.parent), str(yosys.parent), environment.get("PATH", os.defpath)))
        command = ("make", "tunereport", f"PRIVATE_DIR={materialization['native_environment_mapping']['RUN_DIR']}",
                   f"DESIGN_CONFIG={materialization['private_config']}")
        completed = subprocess.run(command, cwd=materialization["flow"], env=environment,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
        (root / "orfs_agent_native_make.log").write_text(completed.stdout, encoding="utf-8", errors="replace")
        if completed.returncode != 0:
            raise RuntimeError(f"upstream-style make tunereport exited {completed.returncode}")
        metrics = _copy_report(root, materialization)
        provenance = {"adapter": "orfs-agent-paper-reproduction-executor",
                      "source": source_receipt, "paper_orfs": flow_receipt,
                      "openroad": str(openroad), "yosys": str(yosys),
                      "full_upstream_domain": list(PARAMETERS),
                      "note": "candidate-specific CLK is original ORFS-Agent reproduction semantics, not fair fixed-SDC PPA"}
        _write(root / "reproduction_provenance.json", provenance)
        artifacts = [
            {"kind": "optimizer_input_manifest", "path": "candidate_materialization.json"},
            {"kind": "optimizer_dataset", "path": "candidate_metrics.json"},
            {"kind": "upstream_source_lock", "path": "reproduction_provenance.json"},
            {"kind": "log", "path": "orfs_agent_native_make.log"},
            {"kind": "report", "path": "candidate_metrics.json"},
        ]
        args.result.write_text(json.dumps(_result(status="succeeded", code=0, started=started,
            artifacts=artifacts, provenance=provenance), indent=2), encoding="utf-8")
        return 0
    except Exception as exc:
        args.result.write_text(json.dumps(_result(status="failed", code=2, started=started,
            artifacts=[], provenance={"adapter": "orfs-agent-paper-reproduction-executor"},
            failure={"category": "adapter_error", "message": str(exc)}), indent=2), encoding="utf-8")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
