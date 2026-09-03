from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.aggregate_orfs_agent_equal_budget_campaign import aggregate


def _write_arm(root: Path, *, optimizer: str, reference: dict | None = None,
               candidates: int = 250) -> None:
    root.mkdir()
    reference = reference or {"platform": "sky130hd", "design": "aes", "frozen_sdc": {"sha256": "a" * 64}}
    receipt = {
        "status": "completed", "completion_reason": "candidate_confirmed_after_independent_repetitions",
        "reference": reference, "optimizer": {"plugin": optimizer},
        "resource_policy": {"max_parallel": 8, "orfs_cores_per_run": 4},
        "protocol": {"warmup_count": 50, "candidate_budget": 250},
        "target_feasibility": {"domain_digest": "b" * 64},
    }
    row = {
        "status": "succeeded", "feasible": True,
        "metrics": {"optimizer_objective": .95}, "run_id": "run-1",
    }
    checkpoint = {"state": {
        "status": "completed", "warmup_runs": [{} for _ in range(50)],
        "candidate_count": candidates, "history": [{"results": [{"terminal_observations": [row]}]}],
        "baseline_objective": 1.0, "baseline_metrics": {"area_um2": 1.0},
        "baseline_observations": [{}, {}, {}],
        "final_confirmation": {"candidate_id": "best", "objective_median": .94,
                               "confirmed_improvement": True, "terminal_observations": [row, row, row]},
    }}
    (root / "campaign-receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    (root / "checkpoint-export.json").write_text(json.dumps(checkpoint), encoding="utf-8")


def test_aggregation_requires_matching_protocol_and_equal_completed_budget(tmp_path: Path):
    agent, control = tmp_path / "agent", tmp_path / "control"
    _write_arm(agent, optimizer="orfs-agent@2025.1")
    _write_arm(control, optimizer="seeded-random-control@1.0.0")
    report = aggregate(agent_output=agent, control_output=control)
    assert report["comparability"]["status"] == "passed"
    assert report["arms"]["orfs_agent"]["screening"]["candidate_count"] == 250
    assert report["statistical_claim"]["status"] == "not_established"


def test_aggregation_fails_closed_for_an_unequal_arm(tmp_path: Path):
    agent, control = tmp_path / "agent", tmp_path / "control"
    _write_arm(agent, optimizer="orfs-agent@2025.1")
    _write_arm(control, optimizer="seeded-random-control@1.0.0", candidates=249)
    with pytest.raises(ValueError, match="equal screening budget"):
        aggregate(agent_output=agent, control_output=control)
