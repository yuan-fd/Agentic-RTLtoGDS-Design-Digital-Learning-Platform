from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_orfs_agent_intake_lock_pins_source_license_and_execution_boundary():
    source = json.loads((ROOT / "integrations/orfs_agent/source.lock.json").read_text())
    environment = json.loads((ROOT / "integrations/orfs_agent/environment.lock.json").read_text())

    assert source["repository"] == "https://github.com/ABKGroup/ORFS-Agent.git"
    assert source["commit"] == "730f1fa11f9c17c0aaac332412af2b2538f42e9b"
    assert source["license"] == "BSD-3-Clause"
    assert source["integration_class"] == "external-source-with-runtime-adapter"
    assert "SSH" in " ".join(source["known_upstream_assumptions"])
    assert environment["source"]["commit"] == source["commit"]
    assert environment["source"]["license"]["license_sha256"] == (
        "243601633b171278cd98f9ea495cbfc74aad9d7fc062c6e7c81e20d1fc44a22f"
    )
    assert environment["reproduction_boundary"]["upstream_full_launcher"].startswith("blocked:")


def test_orfs_agent_clean_smoke_receipt_references_pinned_source_and_no_qor_claim():
    evidence = (ROOT / "docs/evidence/P5_ORFS_AGENT_BOUNDED_ADMISSION_20260902.md").read_text()
    assert "730f1fa11f9c17c0aaac332412af2b2538f42e9b" in evidence
    assert "clean detached checkout" in evidence
    assert "not a QoR-improvement" in evidence
    assert "077705bf27343d78146f2dcc1e17cbc339c46f229e72c7703e074d54740dbc7a" in evidence
