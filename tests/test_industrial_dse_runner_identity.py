from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_runner_exposes_canonical_cell_identity_before_openroad_start() -> None:
    path = ROOT / "scripts/run_industrial_dse_experiment.py"
    spec = importlib.util.spec_from_file_location("industrial_dse_runner_identity", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest = {"study": "r26", "seed": 1103, "parameters": {"b": 2, "a": 1}}
    expected = hashlib.sha256(json.dumps(
        manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert module._digest(manifest) == expected
    assert module._frozen_controller_digest({
        "reproducibility": {"source_snapshot": {"controller": {"digest": "frozen"}}}
    }) == "frozen"
    assert module._frozen_controller_digest({}) is None
