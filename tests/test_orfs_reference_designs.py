from pathlib import Path

import pytest

from openroad_platform_execution import (
    ORFS_AGENT_PAPER_ORFS_COMMIT, load_orfs_agent_paper_reference_design,
    load_orfs_reference_design,
)
from openroad_platform_execution import orfs_reference_designs as reference_module


ORFS = Path(__file__).resolve().parents[2] / "OpenROAD-flow-scripts"


@pytest.mark.parametrize("platform,design,top", [
    ("asap7", "aes", "aes_cipher_top"),
    ("asap7", "jpeg", "jpeg_encoder"),
    ("asap7", "ibex", "ibex_core"),
    ("sky130hd", "aes", "aes_cipher_top"),
    ("sky130hd", "jpeg", "jpeg_encoder"),
    ("sky130hd", "ibex", "ibex_core"),
])
def test_primary_reference_bundle_is_complete_and_builds_valid_request(platform, design, top):
    recipe = load_orfs_reference_design(ORFS, platform=platform, design=design)
    assert recipe.top == top
    assert len(recipe.source_fingerprint) == 64
    assert recipe.orfs_commit != "unknown"
    parameters = dict(recipe.native_baseline_overrides)
    request = recipe.request(
        flow_parameters=parameters, or_seed=101,
        run_id=f"test-{platform}-{design}",
    )
    request.validate()
    assert request.top == top
    assert request.sdc_path == str(recipe.sdc_path)
    assert request.labels["design_bundle_sha256"] == recipe.source_fingerprint
    if design == "ibex":
        assert len(request.rtl_files) == 21
        assert request.synth_hdl_frontend == "slang"
        assert request.design_options["openroad_hierarchical"] == 1
        if platform == "asap7":
            assert request.clock_period_ns == 1.468
            assert Path(request.sdc_path).name == "constraint_pos_slack.sdc"


def test_unregistered_reference_design_is_rejected():
    with pytest.raises(ValueError, match="unregistered"):
        load_orfs_reference_design(ORFS, platform="asap7", design="toy")


def _paper_checkout(tmp_path: Path) -> Path:
    root = tmp_path / "paper-orfs"
    source = root / "flow/designs/src/aes"
    source.mkdir(parents=True)
    for name in (
        "aes_cipher_top.v", "aes_inv_cipher_top.v", "aes_inv_sbox.v",
        "aes_key_expand_128.v", "aes_rcon.v", "aes_sbox.v", "timescale.v",
    ):
        (source / name).write_text(
            "module aes_cipher_top(input clk); endmodule\n"
            if name == "aes_cipher_top.v" else f"// {name}\n",
            encoding="utf-8",
        )
    sdc = root / "flow/designs/sky130hd/aes/constraint.sdc"
    sdc.parent.mkdir(parents=True)
    sdc.write_text("create_clock -period 4.5 [get_ports clk]\n", encoding="utf-8")
    (sdc.parent / "fastroute.tcl").write_text(
        "set_global_routing_layer_adjustment met1-met5 0.4\n",
        encoding="utf-8",
    )
    return root


def test_orfs_agent_paper_reference_is_distinct_and_complete(tmp_path, monkeypatch):
    root = _paper_checkout(tmp_path)
    monkeypatch.setattr(
        reference_module, "_git_output",
        lambda _root, *args: (ORFS_AGENT_PAPER_ORFS_COMMIT
                              if args == ("rev-parse", "HEAD") else ""),
    )
    recipe = load_orfs_agent_paper_reference_design(root)
    assert recipe.platform == "sky130hd"
    assert recipe.design == "aes"
    assert recipe.top == "aes_cipher_top"
    assert recipe.clock_period_ns == 4.5
    assert recipe.sdc_path.read_text(encoding="utf-8").find("4.5") >= 0
    assert recipe.fast_route_tcl_path is not None
    assert recipe.fast_route_tcl_path.read_text(encoding="utf-8").find("0.4") >= 0
    assert len(recipe.rtl_files) == 7
    assert recipe.native_baseline_overrides == {
        "core_utilization_pct": 20, "place_density": .6,
        "tns_end_percent": 100,
    }
    assert recipe.design_options == {"remove_abc_buffers": 1}
    assert recipe.orfs_commit == ORFS_AGENT_PAPER_ORFS_COMMIT


def test_orfs_agent_paper_reference_rejects_wrong_commit(tmp_path, monkeypatch):
    root = _paper_checkout(tmp_path)
    monkeypatch.setattr(reference_module, "_git_output", lambda *_args: "0" * 40)
    with pytest.raises(ValueError, match="requires ORFS commit"):
        load_orfs_agent_paper_reference_design(root)
