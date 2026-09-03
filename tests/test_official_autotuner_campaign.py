import importlib.util
from pathlib import Path


def _module():
    path = (Path(__file__).resolve().parents[1] /
            "scripts/run_official_autotuner_campaign.py")
    spec = importlib.util.spec_from_file_location("official_campaign", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def _runner_module():
    path = (Path(__file__).resolve().parents[1] /
            "scripts/run_official_autotuner_baseline.py")
    spec = importlib.util.spec_from_file_location("official_runner_snapshot", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_official_campaign_cells_are_deterministic_and_protocol_scoped():
    module = _module()
    protocol = {"primary_blocks": [
        {"platform": "asap7", "design": "aes"},
        {"platform": "sky130hd", "design": "ibex"},
    ]}
    cells = module.build_cells(
        protocol, blocks=["asap7/aes"], seeds=[1103, 2207],
        budget=600, mode="paper")
    assert [item["cell_id"] for item in cells] == [
        "asap7-aes-official-hyperopt-o1103-b600",
        "asap7-aes-official-hyperopt-o2207-b600",
    ]
    assert all(item["design"] == "aes" and item["platform"] == "asap7"
               for item in cells)
    snapshot = module._controller_source_snapshot()
    assert snapshot["file_count"] > 20
    assert any(item["path"] == "scripts/run_official_autotuner_baseline.py"
               for item in snapshot["files"])
    assert snapshot == _runner_module()._controller_source_snapshot()
    assert any(item["path"] == "scripts/analyze_industrial_dse_study.py"
               for item in snapshot["files"])
