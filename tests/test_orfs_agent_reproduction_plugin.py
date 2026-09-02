from __future__ import annotations

from pathlib import Path

from openroad_platform_execution.orfs_agent_reproduction_plugin import (
    ORFS_AGENT_REPRODUCTION_PLUGIN_ID,
    UPSTREAM_PARAMETERS,
    build_orfs_agent_reproduction_task,
    orfs_agent_reproduction_manifest,
)


def _candidate() -> dict[str, float | int]:
    return {"CLK": 4.5, "UTIL": 20, "TNS_End_Percent": 100, "GP_PAD": 0,
            "DP_PAD": 0, "DPO": 1, "PIN_ADJ": .4, "UP_ADJ": .4,
            "LB_ADDON": .4936, "HIER_SYNTH": 0, "CTS_CSIZE": 10, "CTS_CDIA": 80}


def test_task_preserves_all_upstream_fields() -> None:
    task = build_orfs_agent_reproduction_task(
        project_id="paper", design_id="aes", design="aes", platform_name="sky130hd",
        candidate=_candidate(), task_id="orfs-agent-paper-unit",
    )
    assert task.plugin_id == ORFS_AGENT_REPRODUCTION_PLUGIN_ID
    assert tuple(task.inputs["candidate"]) == UPSTREAM_PARAMETERS
    assert task.labels["reproduction_mode"] == "variable-clock-upstream-semantics"


def test_manifest_is_process_adapter_ready(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    openroad, yosys = tmp_path / "openroad", tmp_path / "yosys"
    openroad.touch(); yosys.touch()
    manifest = orfs_agent_reproduction_manifest(
        source=root / "var/external-sources/orfs-agent-730f1fa-clean-20260901",
        paper_orfs=root / "var/toolchains/orfs-ce8d36a-paper",
        openroad_bin=openroad, yosys_bin=yosys,
    )
    assert manifest.plugin_id == ORFS_AGENT_REPRODUCTION_PLUGIN_ID
    assert "optimizer.l2.paper-reproduction" in manifest.capabilities
