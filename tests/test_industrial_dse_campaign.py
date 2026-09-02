import importlib.util
from pathlib import Path
from types import SimpleNamespace


def _module():
    path = Path(__file__).resolve().parents[1] / "scripts/run_industrial_dse_campaign.py"
    spec = importlib.util.spec_from_file_location("industrial_campaign", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def _runner_module():
    path = Path(__file__).resolve().parents[1] / "scripts/run_industrial_dse_experiment.py"
    spec = importlib.util.spec_from_file_location("industrial_runner_snapshot", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_campaign_cells_are_deterministic_and_domain_separated():
    protocol = {
        "primary_blocks": [
            {"platform": "asap7", "design": "aes"},
            {"platform": "sky130hd", "design": "ibex"},
        ],
    }
    cells = _module().build_cells(
        protocol, arms=["random", "portfolio"], seeds=[1103, 2207],
        blocks=["asap7/aes"], budget=50, mode="preflight")
    assert [item["cell_id"] for item in cells] == [
        "asap7-aes-random-o1103-b50", "asap7-aes-random-o2207-b50",
        "asap7-aes-portfolio-o1103-b50", "asap7-aes-portfolio-o2207-b50",
    ]
    assert cells[0]["search_domain"] == "official_autotuner_independent_v2"
    assert cells[-1]["search_domain"] == "calibrated_full"
    assert _module()._controller_source_snapshot() == \
        _runner_module()._controller_source_snapshot()
    assert _module()._frozen_controller_digest({
        "reproducibility": {"source_snapshot": {"controller": {"digest": "frozen"}}}
    }) == "frozen"


def test_ablation_campaign_uses_only_full_portfolio_and_distinct_cell_ids():
    protocol = {"primary_blocks": [{"platform": "asap7", "design": "aes"}]}
    cells = _module().build_cells(
        protocol, arms=["random", "portfolio"], seeds=[1103],
        blocks=[], budget=200, mode="paper",
        ablations=["no_gp", "no_memory"])
    assert [item["cell_id"] for item in cells] == [
        "asap7-aes-portfolio-ano_gp-o1103-b200",
        "asap7-aes-portfolio-ano_memory-o1103-b200",
    ]
    assert all(item["arm"] == "portfolio" for item in cells)
    assert all(item["search_domain"] == "calibrated_full" for item in cells)


def test_campaign_log_does_not_prepopulate_runner_owned_cell_directory(tmp_path, monkeypatch):
    module = _module()
    cell = {
        "cell_id": "asap7-aes-stateful_portfolio-o1103-b1",
        "platform": "asap7", "design": "aes", "arm": "stateful_portfolio",
        "ablation": "none", "optimizer_seed": 1103, "budget": 1,
        "mode": "preflight", "search_domain": "calibrated_full",
    }
    observed = {}

    def fake_run(command, **_kwargs):
        output = Path(command[command.index("--output") + 1])
        observed["output_exists_before_runner"] = output.exists()
        observed["output_entries_before_runner"] = (
            list(output.iterdir()) if output.exists() else [])
        output.mkdir(parents=True, exist_ok=True)
        (output / "checkpoint-export.json").write_text(
            '{"state": {"status": "completed"}}', encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    row = module._run_cell(
        cell, root=tmp_path, protocol=tmp_path / "protocol.json",
        calibration=tmp_path / "calibration.json", orfs_root=tmp_path / "orfs",
        toolchain_lock=tmp_path / "lock.json", controller_source_sha256="source",
        python_environment_sha256="environment", max_parallel=1, orfs_cores=1,
    )
    assert observed == {"output_exists_before_runner": False,
                        "output_entries_before_runner": []}
    assert row["terminal_status"] == "completed"
    assert Path(row["log"]).parent.name == "controller-logs"
