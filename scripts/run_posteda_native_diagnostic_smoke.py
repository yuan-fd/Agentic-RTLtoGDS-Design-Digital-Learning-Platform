#!/usr/bin/env python3
"""Run one pinned PostEDA-Bench public DRC parser, then score it privately."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "var/external-sources/posteda-bench-51884e5-clean"
LOCK = ROOT / "integrations/posteda_bench/source.lock.json"
COMMIT = "51884e5f20e6e199219cec87c1c779a3dfab95bc"
TREE = "c5ccdf6e7165bcc9749e10dacd023bfe5cde20a4"
TASK_ID = "drc_essential/L1/q1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(SOURCE), *args], text=True).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--klayout", type=Path, default=Path("/share/home/yuanwenjie/bin/klayout"))
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    klayout = args.klayout.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("refusing to overwrite PostEDA native smoke evidence")
    if not klayout.is_file():
        raise FileNotFoundError("KLayout executable is unavailable")
    output.mkdir(parents=True, exist_ok=True)

    lock = json.loads(LOCK.read_text())
    task = SOURCE / "benchmark/drc_bench" / TASK_ID
    workspace = output / "native-workspace"
    workspace.mkdir()
    # Deliberately exclude info.json and GDS from the public analyzer workspace.
    for name in ("drc_error_collection.py", "6_drc_count.rpt"):
        shutil.copy2(task / name, workspace / name)
    before = {name: _sha256(workspace / name)
              for name in ("drc_error_collection.py", "6_drc_count.rpt")}
    command = [str(klayout), "-b", "-r", "drc_error_collection.py"]
    result = subprocess.run(
        command, cwd=workspace, text=True, capture_output=True, timeout=120,
        env={"PATH": f"{klayout.parent}:/usr/bin:/bin"}, check=False)
    (output / "native.stdout.log").write_text(result.stdout)
    (output / "native.stderr.log").write_text(result.stderr)
    (output / "command.json").write_text(json.dumps({
        "argv": command, "cwd": "native-workspace", "exit_code": result.returncode,
        "timeout_seconds": 120, "network": "not requested",
        "hidden_info_present_during_analysis": (workspace / "info.json").exists(),
    }, indent=2) + "\n")

    categories = re.findall(r"^---\s+([^|]+?)\s+\|", result.stdout, re.MULTILINE)
    item_count = len(re.findall(r"^\[\d+\]\s+\{", result.stdout, re.MULTILINE))
    # Private scoring begins only after native stdout is durable.
    hidden = json.loads((task / "info.json").read_text())
    expected = dict(hidden["init_error_types"])
    observed = {category: result.stdout.count(f"'category': '{category}'")
                for category in categories}
    after = {name: _sha256(workspace / name) for name in before}
    status = _git("status", "--porcelain")
    checks = {
        "pinned_commit": _git("rev-parse", "HEAD") == COMMIT,
        "pinned_tree": _git("rev-parse", "HEAD^{tree}") == TREE,
        "clean_checkout": status == "",
        "lock_matches_checkout": lock["required_commit"] == COMMIT
            and lock["required_tree"] == TREE,
        "license_hash_matches": _sha256(SOURCE / "LICENSE") ==
            lock["license"]["sha256"],
        "native_klayout_succeeded": result.returncode == 0,
        "upstream_entrypoint_executed": "drc_error_collection.py" in command,
        "hidden_label_firewall": not (workspace / "info.json").exists(),
        "public_inputs_unchanged": before == after,
        "one_public_marker_parsed": item_count == 1,
        "private_type_and_count_match": observed == expected == {"WELL.W.1": 1},
    }
    summary = {
        "schema_version": 1,
        "kind": "posteda-bench-native-diagnostic-smoke",
        "accepted": all(checks.values()),
        "source_lock": {"path": str(LOCK.relative_to(ROOT)),
                        "sha256": _sha256(LOCK)},
        "upstream": {"url": lock["canonical_upstream"], "commit": COMMIT,
                     "tree": TREE, "license": lock["license"]},
        "task_id": TASK_ID,
        "public_analysis": {"categories": categories, "item_count": item_count,
                            "report_sha256": before["6_drc_count.rpt"]},
        "private_score": {"expected_type_counts": expected,
                          "observed_type_counts": observed,
                          "exact_match": observed == expected},
        "artifacts": {
            "stdout": {"path": "native.stdout.log",
                       "sha256": _sha256(output / "native.stdout.log")},
            "stderr": {"path": "native.stderr.log",
                       "sha256": _sha256(output / "native.stderr.log")},
            "command": {"path": "command.json",
                        "sha256": _sha256(output / "command.json")},
        },
        "checks": checks,
        "claim_boundary": (
            "One pinned PostEDA-Bench q1 report parsed by its native KLayout entrypoint, "
            "with hidden labels consulted only after public output was persisted. This is "
            "not an agent repair, official SR/ERR result, or broad benchmark score."),
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
