from __future__ import annotations

import importlib.util
import hashlib
import json
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


def test_measurement_report_has_distinct_store_key_and_hashes_metrics(tmp_path: Path) -> None:
    metrics = {"schema_version": 1, "ECP_final": 4.7,
               "detailedroute__route__wirelength": 589825.0}
    metrics_path = tmp_path / "candidate_metrics.json"
    metrics_path.write_text(json.dumps(metrics), encoding="utf-8")
    report = adapter._write_measurement_index(
        tmp_path, candidate=candidate(), objective="ECP", metrics=metrics)
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert report.name == "candidate_execution_report.json"
    assert payload["authority"] == "adapter-index-not-canonical-qor"
    assert payload["metrics_artifact"]["path"] == metrics_path.name
    assert payload["metrics_artifact"]["sha256"] == hashlib.sha256(
        metrics_path.read_bytes()).hexdigest()


def test_upstream_tunereport_outputs_are_registered_without_claiming_gds(tmp_path: Path) -> None:
    result = tmp_path / "work/results/sky130hd/aes/candidate"
    result.mkdir(parents=True)
    for name in ("6_final.odb", "6_final.def", "6_final.v",
                 "6_final.sdc", "6_final.spef"):
        (result / name).write_text(name, encoding="utf-8")
    artifacts = adapter._final_physical_artifacts(
        tmp_path, {"expected_result_directory": str(result)})
    assert [item["kind"] for item in artifacts] == [
        "odb", "def", "netlist", "sdc", "spef"]
    assert all(not Path(item["path"]).is_absolute() for item in artifacts)
    assert "gds" not in {item["kind"] for item in artifacts}


def test_materialization_uses_native_job_name_and_recursive_make_paths(tmp_path: Path) -> None:
    value = candidate()
    value.update({"CLK": 12.05838653349147, "LB_ADDON": 0.17091890800225892,
                  "PIN_ADJ": 0.4127762725908385, "UP_ADJ": 0.4407358491323956})
    receipt = adapter._materialize(
        tmp_path, source=ROOT / "var/external-sources/orfs-agent-730f1fa-clean-20260901",
        paper_orfs=Path("/tmp/orfs-agent-paper-orfs-clean"), platform="sky130hd",
        design="aes", candidate=value,
    )
    variant = receipt["native_environment_mapping"]["FLOW_VARIANT"]
    native = adapter._upstream_execution_candidate(value)
    assert receipt["candidate"] == value
    assert receipt["native_execution_candidate"] == native
    assert native["CLK"] == 12.058
    assert native["LB_ADDON"] == 0.171
    assert native["PIN_ADJ"] == 0.413
    assert native["UP_ADJ"] == 0.441
    assert variant == adapter._upstream_job_name(
        design="aes", platform="sky130hd", candidate=native)
    assert "__CTS_CDIA_80__PIN_ADJ_0.413__UP_ADJ_0.441" in variant
    assert len(variant.encode("utf-8")) <= 255
    assert receipt["execution_mapping"]["owner"] == "upstream ORFS-Agent"
    assert receipt["native_environment_mapping"]["IO_PLACER_H"] == "met3"
    assert receipt["native_environment_mapping"]["NUM_CORES"] == "4"
    assert receipt["native_environment_mapping"]["FLOW_HOME"] == receipt["flow"]
    assert receipt["private_flow_compatibility_patch"][0]["path"] == "util/utils.mk"
    assert receipt["private_flow_compatibility_patch"][1]["path"] == "scripts/write_ref_sdc.tcl"
    assert receipt["private_flow_compatibility_patch"][2]["path"] == "Makefile"
    assert receipt["private_flow_compatibility_patch"][3]["path"] == "scripts/synth_hier_report.tcl"
    patched_utils = (tmp_path / "orfs-flow/util/utils.mk").read_text(encoding="utf-8")
    assert "MAKEFLAGS%" in patched_utils
    assert "RESULTS_DIR%" in patched_utils
    assert receipt["expected_result_directory"].endswith(f"sky130hd/aes/{variant}")
    patched_hier = (tmp_path / "orfs-flow/scripts/synth_hier_report.tcl").read_text(encoding="utf-8")
    assert "[A-Za-z_][A-Za-z0-9_$]*" in patched_hier
