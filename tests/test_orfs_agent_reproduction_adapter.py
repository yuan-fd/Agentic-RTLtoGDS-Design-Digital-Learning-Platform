from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "integrations/orfs_agent/orfs_agent_reproduction_adapter.py"
spec = importlib.util.spec_from_file_location("orfs_agent_reproduction_adapter", ADAPTER_PATH)
assert spec and spec.loader
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


def candidate() -> dict[str, float | int]:
    return {"CLK": 4.5, "UTIL": 20, "TNS_End_Percent": 100, "GP_PAD": 0,
            "DP_PAD": 0, "DPO": 1, "PIN_ADJ": .4, "UP_ADJ": .4,
            "LB_ADDON": .4936, "HIER_SYNTH": 0, "CTS_CSIZE": 10, "CTS_CDIA": 80}


def test_full_upstream_candidate_is_preserved_without_platform_projection() -> None:
    value = adapter.validate_candidate(candidate(), platform="sky130hd")
    assert tuple(value) == adapter.PARAMETERS
    assert value["CLK"] == 4.5
    assert value["PIN_ADJ"] == .4
    assert value["HIER_SYNTH"] == 0


def test_reproduction_does_not_inject_legacy_padding_constraint() -> None:
    value = candidate(); value["GP_PAD"] = 0; value["DP_PAD"] = 3
    assert adapter.validate_candidate(value, platform="sky130hd")["DP_PAD"] == 3


def test_candidate_rejects_missing_or_out_of_domain_field() -> None:
    value = candidate(); value.pop("CLK")
    with pytest.raises(ValueError, match="exactly the upstream 12"):
        adapter.validate_candidate(value, platform="sky130hd")
    value = candidate(); value["CTS_CSIZE"] = 41
    with pytest.raises(ValueError, match="outside upstream range"):
        adapter.validate_candidate(value, platform="sky130hd")


def test_materialization_uses_native_job_name_and_recursive_make_paths(tmp_path: Path) -> None:
    value = candidate()
    receipt = adapter._materialize(
        tmp_path, source=ROOT / "var/external-sources/orfs-agent-730f1fa-clean-20260901",
        paper_orfs=Path("/tmp/orfs-agent-paper-orfs-clean"), platform="sky130hd",
        design="aes", candidate=value,
    )
    variant = receipt["native_environment_mapping"]["FLOW_VARIANT"]
    assert variant == adapter._upstream_job_name(design="aes", platform="sky130hd", candidate=value)
    assert "__CTS_CDIA_80__PIN_ADJ_0.4__UP_ADJ_0.4" in variant
    assert receipt["native_environment_mapping"]["IO_PLACER_H"] == "met3"
    assert receipt["native_environment_mapping"]["NUM_CORES"] == "4"
    assert receipt["native_environment_mapping"]["FLOW_HOME"] == receipt["flow"]
    assert receipt["private_flow_compatibility_patch"]["path"] == "util/utils.mk"
    patched_utils = (tmp_path / "orfs-flow/util/utils.mk").read_text(encoding="utf-8")
    assert "MAKEFLAGS%" in patched_utils
    assert "RESULTS_DIR%" in patched_utils
    assert receipt["expected_result_directory"].endswith(f"sky130hd/aes/{variant}")
