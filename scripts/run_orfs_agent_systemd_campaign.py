#!/usr/bin/env python3
"""Launch the frozen ORFS-Agent campaign under one user-systemd cgroup.

This is deliberately a lifecycle supervisor, not an optimizer.  It runs the
existing target-feasibility preflight, verifies its immutable receipt/report
boundary, then runs the existing official-scale campaign.  Running the two
controllers in one transient user service prevents a parent-controller loss
from leaving long-lived adapter/OpenROAD processes outside the campaign's
lifecycle authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]


def _command(*, preflight_output: Path | None, reuse_preflight: Path | None,
             supervisor_output: Path, formal_output: Path, control_output: Path,
             aggregate_output: Path, orfs_agent_source: Path | None, max_parallel: int,
             orfs_cores_per_run: int, stage_timeout: int,
             flow_timeout: int) -> list[str]:
    """Build the immutable controller command run *inside* systemd."""
    command = [
        sys.executable, str(Path(__file__).resolve()), "--worker",
        "--supervisor-output", str(supervisor_output),
        "--formal-output", str(formal_output),
        "--control-output", str(control_output),
        "--aggregate-output", str(aggregate_output),
        "--max-parallel", str(max_parallel),
        "--orfs-cores-per-run", str(orfs_cores_per_run),
        "--stage-timeout", str(stage_timeout),
        "--flow-timeout", str(flow_timeout),
    ]
    if reuse_preflight is not None:
        command.extend(("--reuse-preflight", str(reuse_preflight)))
    elif preflight_output is not None:
        command.extend(("--preflight-output", str(preflight_output)))
    else:
        raise ValueError("worker needs a preflight output or a completed preflight to reuse")
    if orfs_agent_source is not None:
        command.extend(("--orfs-agent-source", str(orfs_agent_source)))
    return command


def _write_supervisor_receipt(root: Path, payload: dict) -> None:
    """Write lifecycle evidence independently of systemd stdout/journal access."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / "supervisor-receipt.json"
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
    temporary.replace(path)


def _validate_preflight(root: Path) -> Path:
    receipt_path = root / "preflight-receipt.json"
    report_path = root / "target-feasibility-report.json"
    if not receipt_path.is_file() or not report_path.is_file():
        raise RuntimeError("FAIL_CLOSED: preflight completed without required receipt/report")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("status") != "completed":
        raise RuntimeError("FAIL_CLOSED: preflight receipt is not completed")
    expected = receipt.get("report_sha256")
    actual = hashlib.sha256(report_path.read_bytes()).hexdigest()
    if not isinstance(expected, str) or actual != expected:
        raise RuntimeError("FAIL_CLOSED: preflight report digest mismatch")
    return report_path


def _worker(args: argparse.Namespace) -> int:
    if bool(args.preflight_output) == bool(args.reuse_preflight):
        raise ValueError("select exactly one of --preflight-output or --reuse-preflight")
    preflight = (args.reuse_preflight if args.reuse_preflight else args.preflight_output).resolve()
    formal = args.formal_output.resolve()
    control = args.control_output.resolve()
    aggregate = args.aggregate_output.resolve()
    supervisor = args.supervisor_output.resolve()
    started = datetime.now(timezone.utc).isoformat()
    receipt = {
        "schema_version": 1,
        "status": "running",
        "started_at": started,
        "preflight": str(preflight),
        "formal_output": str(formal),
        "control_output": str(control),
        "aggregate_output": str(aggregate),
        "orfs_agent_source": (str(args.orfs_agent_source.resolve())
                              if args.orfs_agent_source is not None else None),
        "resource_policy": {
            "max_parallel": args.max_parallel,
            "orfs_cores_per_run": args.orfs_cores_per_run,
            "stage_timeout_seconds": args.stage_timeout,
            "flow_timeout_seconds": args.flow_timeout,
        },
    }
    _write_supervisor_receipt(supervisor, receipt)
    def finish(status: str, *, phase: str, returncode: int | None = None,
               message: str | None = None) -> int:
        _write_supervisor_receipt(supervisor, {
            **receipt, "status": status, "ended_at": datetime.now(timezone.utc).isoformat(),
            "phase": phase, "returncode": returncode, "message": message,
        })
        return 0 if status == "completed" else 1
    try:
        if formal.exists() or control.exists() or aggregate.exists():
            raise RuntimeError("FAIL_CLOSED: formal, control, or aggregate output already exists")
        if args.reuse_preflight is None:
            preflight_cmd = [
                sys.executable, str(ROOT / "scripts/run_orfs_agent_target_feasibility_preflight.py"),
                "--output", str(preflight), "--max-parallel", str(args.max_parallel),
                "--orfs-cores-per-run", str(args.orfs_cores_per_run),
                "--stage-timeout", str(args.stage_timeout),
                "--flow-timeout", str(args.flow_timeout),
            ]
            rc = subprocess.run(preflight_cmd, cwd=ROOT, check=False).returncode
            if rc != 0:
                return finish("failed", phase="preflight", returncode=rc,
                              message="target-feasibility preflight returned non-zero")
        report = _validate_preflight(preflight)
        formal_cmd = [
            sys.executable, str(ROOT / "scripts/run_orfs_agent_paper_campaign.py"),
            "--output", str(formal), "--platform", "sky130hd", "--design", "aes",
            "--target-feasibility-report", str(report), "--max-parallel", str(args.max_parallel),
            "--orfs-cores-per-run", str(args.orfs_cores_per_run),
            "--stage-timeout", str(args.stage_timeout),
            "--flow-timeout", str(args.flow_timeout),
        ]
        if args.orfs_agent_source is not None:
            formal_cmd.extend(("--orfs-agent-source", str(args.orfs_agent_source.resolve())))
        rc = subprocess.run(formal_cmd, cwd=ROOT, check=False).returncode
        if rc != 0:
            return finish("failed", phase="formal", returncode=rc,
                          message="formal controller returned non-zero; inspect its preserved Runtime evidence")
        control_cmd = [
            sys.executable, str(ROOT / "scripts/run_orfs_agent_paper_campaign.py"),
            "--output", str(control), "--optimizer-arm", "seeded_random_control",
            "--platform", "sky130hd", "--design", "aes",
            "--target-feasibility-report", str(report), "--max-parallel", str(args.max_parallel),
            "--orfs-cores-per-run", str(args.orfs_cores_per_run),
            "--stage-timeout", str(args.stage_timeout),
            "--flow-timeout", str(args.flow_timeout),
        ]
        rc = subprocess.run(control_cmd, cwd=ROOT, check=False).returncode
        if rc != 0:
            return finish("failed", phase="random_control", returncode=rc,
                          message="random-control controller returned non-zero; inspect its preserved Runtime evidence")
        aggregate_cmd = [
            sys.executable, str(ROOT / "scripts/aggregate_orfs_agent_equal_budget_campaign.py"),
            "--agent-output", str(formal), "--control-output", str(control),
            "--output", str(aggregate),
        ]
        rc = subprocess.run(aggregate_cmd, cwd=ROOT, check=False).returncode
        return finish("completed" if rc == 0 else "failed", phase="aggregate", returncode=rc,
                      message=None if rc == 0 else "equal-budget aggregation returned non-zero")
    except Exception as exc:
        return finish("failed", phase="supervisor", returncode=1,
                      message=f"{type(exc).__name__}: {exc}")


def _launch(args: argparse.Namespace) -> int:
    if bool(args.preflight_output) == bool(args.reuse_preflight):
        raise ValueError("select exactly one of --preflight-output or --reuse-preflight")
    preflight = (args.reuse_preflight if args.reuse_preflight else args.preflight_output).resolve()
    supervisor = (args.supervisor_output.resolve() if args.supervisor_output else
                  (args.preflight_output.resolve() if args.preflight_output else None))
    if supervisor is None:
        raise ValueError("--reuse-preflight requires a fresh --supervisor-output")
    formal = args.formal_output.resolve()
    control = args.control_output.resolve()
    aggregate = args.aggregate_output.resolve()
    if (supervisor.exists() or formal.exists() or control.exists() or aggregate.exists()
            or (args.preflight_output is not None and preflight.exists())):
        raise ValueError("supervisor, new preflight (if any), formal, control, and aggregate outputs must all be new")
    supervisor.mkdir(parents=True)
    log = supervisor / "controller.log"
    unit = args.unit or f"orfs-agent-{supervisor.name}".replace("_", "-")
    command = [
        "systemd-run", "--user", "--unit", unit, "--property=Type=exec",
        "--property=KillMode=control-group", f"--property=WorkingDirectory={ROOT}",
        "--property=TimeoutStartSec=infinity", "--property=RuntimeMaxSec=infinity",
        f"--property=StandardOutput=append:{log}",
        f"--property=StandardError=append:{log}", *_command(
            preflight_output=args.preflight_output, reuse_preflight=args.reuse_preflight,
            supervisor_output=supervisor,
            formal_output=formal, control_output=control,
            aggregate_output=aggregate,
            orfs_agent_source=args.orfs_agent_source,
            max_parallel=args.max_parallel, orfs_cores_per_run=args.orfs_cores_per_run,
            stage_timeout=args.stage_timeout, flow_timeout=args.flow_timeout,
        ),
    ]
    completed = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"systemd-run failed: {completed.stdout}")
    state = subprocess.run(
        ["systemctl", "--user", "show", unit, "-p", "MainPID", "-p", "ActiveState"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )
    if state.returncode != 0:
        raise RuntimeError(f"cannot query user-systemd unit: {state.stdout}")
    fields = dict(line.split("=", 1) for line in state.stdout.splitlines() if "=" in line)
    pid = fields.get("MainPID")
    if not pid or pid == "0" or fields.get("ActiveState") not in {"activating", "active"}:
        raise RuntimeError(f"systemd unit did not enter active state: {state.stdout}")
    (supervisor / "controller.pid").write_text(f"{pid}\n", encoding="utf-8")
    print(json.dumps({"unit": unit, "pid": int(pid), "supervisor_output": str(supervisor),
                      "preflight_output": str(preflight), "reused_preflight": bool(args.reuse_preflight),
                      "formal_output": str(formal), "control_output": str(control),
                      "aggregate_output": str(aggregate)}, sort_keys=True))
    return 0


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight-output", type=Path)
    parser.add_argument("--reuse-preflight", type=Path)
    parser.add_argument("--supervisor-output", type=Path)
    parser.add_argument("--formal-output", type=Path, required=True)
    parser.add_argument("--control-output", type=Path, required=True)
    parser.add_argument("--aggregate-output", type=Path, required=True)
    parser.add_argument("--orfs-agent-source", type=Path,
                        help="explicit clean, pinned ORFS-Agent checkout for the GP/EI arm")
    parser.add_argument("--max-parallel", type=int, default=8)
    parser.add_argument("--orfs-cores-per-run", type=int, default=4)
    parser.add_argument("--stage-timeout", type=int, default=3600)
    parser.add_argument("--flow-timeout", type=int, default=7200)
    parser.add_argument("--unit")
    parser.add_argument("--worker", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    if not 1 <= args.max_parallel <= 16 or not 1 <= args.orfs_cores_per_run <= 16:
        raise ValueError("parallelism and cores-per-run must each be 1..16")
    if args.max_parallel * args.orfs_cores_per_run > (os.cpu_count() or 1):
        raise ValueError("max-parallel × orfs-cores-per-run exceeds visible CPU budget")
    if args.stage_timeout <= 0 or args.flow_timeout < args.stage_timeout:
        raise ValueError("flow-timeout must be at least stage-timeout, and both must be positive")
    if args.worker and args.supervisor_output is None:
        raise ValueError("--worker requires --supervisor-output for lifecycle evidence")
    return _worker(args) if args.worker else _launch(args)


if __name__ == "__main__":
    raise SystemExit(main())
