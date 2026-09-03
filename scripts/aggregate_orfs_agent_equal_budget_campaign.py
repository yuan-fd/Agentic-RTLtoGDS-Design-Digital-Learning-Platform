#!/usr/bin/env python3
"""Fail-closed aggregation of ORFS-Agent and equal-budget control evidence.

This program does not rerun a tool, choose a winner, or calculate a claimed
significance result from one optimisation seed.  It proves whether the two
already-finished arms are comparable, summarizes measured outcomes, and makes
the evidence boundary explicit for the later repeated-study analysis.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected an object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def _arm_summary(*, root: Path, receipt: Mapping[str, Any], checkpoint: Mapping[str, Any]) -> dict[str, Any]:
    state = checkpoint.get("state")
    if not isinstance(state, Mapping):
        raise ValueError(f"checkpoint has no state: {root}")
    if receipt.get("status") != "completed" or state.get("status") != "completed":
        raise ValueError(f"arm is not completed: {root}")
    history = state.get("history")
    if not isinstance(history, list):
        raise ValueError(f"arm has no candidate history: {root}")
    results = [item for round_item in history if isinstance(round_item, Mapping)
               for item in round_item.get("results", []) if isinstance(item, Mapping)]
    terminal = [row for item in results for row in item.get("terminal_observations", [])
                if isinstance(row, Mapping)]
    feasible = [row for row in terminal if row.get("status") == "succeeded" and row.get("feasible") is True]
    objectives = [float((row.get("metrics") or {})["optimizer_objective"])
                  for row in feasible
                  if isinstance((row.get("metrics") or {}).get("optimizer_objective"), (int, float))]
    confirmation = state.get("final_confirmation") or {}
    return {
        "root": str(root), "receipt_sha256": _sha256(root / "campaign-receipt.json"),
        "checkpoint_sha256": _sha256(root / "checkpoint-export.json"),
        "optimizer": receipt.get("optimizer"),
        "completion_reason": receipt.get("completion_reason"),
        "screening": {
            "warmup_count": len(state.get("warmup_runs") or []),
            "candidate_count": int(state.get("candidate_count") or 0),
            "terminal_candidate_runs": len(terminal),
            "feasible_candidate_runs": len(feasible),
            "feasibility_rate": len(feasible) / len(terminal) if terminal else None,
            "median_feasible_objective": _median(objectives),
            "best_feasible_objective": min(objectives) if objectives else None,
        },
        "baseline": {
            "objective": state.get("baseline_objective"),
            "metrics": state.get("baseline_metrics"),
            "replicas": len(state.get("baseline_observations") or []),
        },
        "confirmation": {
            "candidate_id": confirmation.get("candidate_id"),
            "objective_median": confirmation.get("objective_median"),
            "confirmed_improvement": confirmation.get("confirmed_improvement"),
            "terminal_runs": len(confirmation.get("terminal_observations") or []),
        },
    }


def aggregate(*, agent_output: Path, control_output: Path) -> dict[str, Any]:
    agent_root, control_root = agent_output.resolve(), control_output.resolve()
    agent_receipt = _read(agent_root / "campaign-receipt.json")
    control_receipt = _read(control_root / "campaign-receipt.json")
    agent_checkpoint = _read(agent_root / "checkpoint-export.json")
    control_checkpoint = _read(control_root / "checkpoint-export.json")
    required_equal = ("reference", "resource_policy", "protocol", "target_feasibility")
    mismatch = {
        key: {"agent": agent_receipt.get(key), "control": control_receipt.get(key)}
        for key in required_equal if agent_receipt.get(key) != control_receipt.get(key)
    }
    if mismatch:
        raise ValueError(f"arms are not comparable: {json.dumps(mismatch, sort_keys=True)}")
    agent = _arm_summary(root=agent_root, receipt=agent_receipt, checkpoint=agent_checkpoint)
    control = _arm_summary(root=control_root, receipt=control_receipt, checkpoint=control_checkpoint)
    protocol = agent_receipt["protocol"]
    expected_warmups, expected_candidates = int(protocol["warmup_count"]), int(protocol["candidate_budget"])
    budget_errors = {
        arm: {name: value for name, value in {
            "warmup_count": summary["screening"]["warmup_count"],
            "candidate_count": summary["screening"]["candidate_count"],
        }.items() if value != {"warmup_count": expected_warmups, "candidate_count": expected_candidates}[name]}
        for arm, summary in (("orfs_agent", agent), ("seeded_random_control", control))
    }
    budget_errors = {arm: values for arm, values in budget_errors.items() if values}
    if budget_errors:
        raise ValueError(f"arms did not consume the frozen equal screening budget: {budget_errors}")
    return {
        "schema_version": 1,
        "kind": "orfs-agent-equal-budget-comparison-v1",
        "comparability": {
            "status": "passed", "equal_fields": list(required_equal),
            "warmup_count": expected_warmups, "candidate_budget": expected_candidates,
            "candidate_budget_equal": True,
        },
        "arms": {"orfs_agent": agent, "seeded_random_control": control},
        "statistical_claim": {
            "status": "not_established",
            "reason": "one completed optimizer-seed campaign per arm is evidence of execution and effect size, not a repeated-study significance result",
            "required_next_evidence": "repeat the complete paired protocol with preregistered independent optimizer seeds before an inferential superiority claim",
        },
        "claim_boundary": (
            "All QoR values summarized here originate from protected-evaluator Runtime artifacts. "
            "The report proves protocol comparability only after its fail-closed checks pass; it does not "
            "turn a one-seed best result into a statistically significant optimisation claim."
        ),
    }


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent-output", type=Path, required=True)
    parser.add_argument("--control-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.exists():
        raise ValueError("aggregate output already exists")
    report = aggregate(agent_output=args.agent_output, control_output=args.control_output)
    _atomic_json(output, report)
    print(json.dumps({"output": str(output), "comparability": report["comparability"]["status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
