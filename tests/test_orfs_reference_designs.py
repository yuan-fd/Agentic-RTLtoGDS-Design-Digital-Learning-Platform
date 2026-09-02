from pathlib import Path

import pytest

from openroad_platform_execution import load_orfs_reference_design


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
