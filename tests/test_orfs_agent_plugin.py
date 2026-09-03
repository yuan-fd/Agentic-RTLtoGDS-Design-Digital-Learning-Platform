from __future__ import annotations

import json
import platform
from dataclasses import replace
from pathlib import Path

from openroad_platform_contracts.platform import RuntimeStatus, TaskSpec
from openroad_platform_execution.registry import PluginRegistry
from openroad_platform_execution.orfs_agent_plugin import (
    build_orfs_agent_dataset_task, build_orfs_agent_native_task,
    build_orfs_agent_initial_warmup_recipes, orfs_agent_plugin_manifest,
)
from openroad_platform_execution.adapter import ProcessAdapter
from openroad_platform_execution.orfs_agent_plugin import _managed_codex_executable
from scripts.run_orfs_agent_paper_campaign import (
    FORMAL_STAGE_TIMEOUT_SECONDS,
    _admitted_domain_capacity,
    build_argument_parser,
)


ROOT = Path(__file__).parents[1]


def test_orfs_agent_manifest_locator_accepts_only_explicit_executable(monkeypatch, tmp_path):
    executable = tmp_path / "managed-codex"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.setenv("OPENROAD_PLATFORM_CODEX_EXECUTABLE", str(executable))
    assert _managed_codex_executable() == str(executable.resolve())


def test_orfs_agent_manifest_locator_preserves_admitted_symlink_launcher(monkeypatch, tmp_path):
    launcher_dir = tmp_path / "nvm" / "bin"
    launcher_dir.mkdir(parents=True)
    target = tmp_path / "node_modules" / "codex.js"
    target.parent.mkdir()
    target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    target.chmod(0o755)
    launcher = launcher_dir / "codex"
    launcher.symlink_to(target)
    monkeypatch.setenv("OPENROAD_PLATFORM_CODEX_EXECUTABLE", str(launcher))
    assert _managed_codex_executable() == str(launcher.absolute())


def test_target_calibrated_formal_campaign_uses_the_preflight_stage_limit():
    """A feasibility receipt cannot be consumed under a stricter timeout."""
    args = build_argument_parser().parse_args([
        "--output", "campaign-evidence", "--platform", "sky130hd", "--design", "aes",
    ])
    assert FORMAL_STAGE_TIMEOUT_SECONDS == 3600
    assert args.stage_timeout == FORMAL_STAGE_TIMEOUT_SECONDS


def test_admitted_domain_capacity_counts_only_legal_complete_coordinates():
    domain = {
        "search_parameter_names": ["core_utilization_pct", "global_placement_padding",
                                   "detail_placement_padding"],
        "admissible_values": {
            "core_utilization_pct": [20, 30],
            "global_placement_padding": [0, 1],
            "detail_placement_padding": [0, 1],
        },
        "fixed_parameters": {
            "tns_end_percent": 100, "enable_dpo": 1, "place_density_lb_addon": .2,
            "cts_cluster_size": 20, "cts_cluster_diameter": 90,
        },
    }
    # DP padding 1 with GP padding 0 is invalid, leaving six legal points.
    assert _admitted_domain_capacity(domain, platform_name="sky130hd") == 6


def _task() -> TaskSpec:
    return TaskSpec(
        task_id="orfs-agent-bridge", project_id="plugin-test", design_id="ibex",
        plugin_id="orfs-agent", timeout_seconds=30,
        expected_artifacts=("optimizer_dataset", "optimizer_input_manifest", "upstream_source_lock"),
        inputs={
            "mode": "materialize_dataset", "design": "ibex", "platform": "asap7",
            "objective": "ECP_final",
            "observations": [{
                "observation_id": "run-001", "feasible": True,
                "artifact_refs": ["runtime:run-001:report"],
                "parameters": {"clock_period_ns": 1.26, "core_utilization_pct": 40,
                               "place_density": .2, "enable_dpo": 0},
                "metrics": {"setup_wns_ns": -.11, "setup_tns_ns": -1.2,
                            "drc_errors": 0, "wirelength_um": 115285.0,
                            "area_um2": 1200.0, "power_mw": 10.0},
            }],
        },
    )


def test_orfs_agent_bridge_materializes_pinned_upstream_dataset(tmp_path):
    registry = PluginRegistry.from_directory(ROOT / "integrations/orfs_agent")
    manifest = registry.resolve("orfs-agent", version="2025.1",
                                capability="optimizer.l2.dataset-bridge",
                                arch=platform.machine())
    execution = ProcessAdapter().execute(manifest, _task(), workspace=tmp_path / "attempt")

    assert execution.result.status is RuntimeStatus.SUCCEEDED
    kinds = {item["kind"] for item in execution.artifacts}
    assert kinds == {"optimizer_dataset", "optimizer_input_manifest", "upstream_source_lock"}
    dataset = json.loads((tmp_path / "attempt" / "orfs_agent_output.json").read_text())
    assert dataset[0]["circuit"] == "ibex"
    assert dataset[0]["pdk"] == "asap7"
    assert dataset[0]["ECP_final"] == 1.37
    assert dataset[0]["platform_observation_id"] == "run-001"
    manifest_data = json.loads((tmp_path / "attempt" / "orfs_agent_input_manifest.json").read_text())
    assert manifest_data["upstream"]["commit"] == "730f1fa11f9c17c0aaac332412af2b2538f42e9b"


def test_orfs_agent_platform_task_builder_and_manifest_do_not_import_an_optimizer():
    task = build_orfs_agent_dataset_task(
        project_id="plugin-test", design_id="ibex", platform_name="asap7",
        objective="ECP_final", observations=_task().inputs["observations"],
    )
    manifest = orfs_agent_plugin_manifest(ROOT / ".external-src/ORFS-Agent")
    assert task.plugin_id == "orfs-agent"
    assert task.inputs["mode"] == "materialize_dataset"
    assert "optimizer.l2.propose" in manifest.capabilities
    assert manifest.environment["ORFS_AGENT_EXPECTED_COMMIT"] == "730f1fa11f9c17c0aaac332412af2b2538f42e9b"


def test_orfs_agent_native_task_builder_only_adds_bounded_invocation_fields():
    task = build_orfs_agent_native_task(
        project_id="plugin-test", design_id="ibex", platform_name="asap7",
        objective="ECP_final", observations=_task().inputs["observations"],
        n_suggestions=2, optimizer_seed=17,
    )
    assert task.inputs["mode"] == "native_agent"
    assert task.inputs["n_suggestions"] == 2
    assert task.inputs["optimizer_seed"] == 17
    assert {"optimizer_candidates", "optimizer_trace"} <= set(task.expected_artifacts)


def test_orfs_agent_initial_warmups_are_frozen_distinct_and_in_the_shared_domain():
    first = build_orfs_agent_initial_warmup_recipes(
        platform_name="nangate45", count=50, seed=401,
    )
    second = build_orfs_agent_initial_warmup_recipes(
        platform_name="nangate45", count=50, seed=401,
    )
    assert first == second
    assert len(first) == 50
    assert len({json.dumps(item["parameters"], sort_keys=True) for item in first}) == 50
    assert all(item["parameters"]["detail_placement_padding"]
               <= item["parameters"]["global_placement_padding"] for item in first)
    assert all(item["origin"]["upstream"] == "OptimizationWorkflow.generate_initial_parameters"
               for item in first)


def test_orfs_agent_target_domain_warmups_are_discrete_legal_and_fail_closed():
    fixed = {
        "tns_end_percent": 100, "global_placement_padding": 3,
        "detail_placement_padding": 3,
        "place_density_lb_addon": .2, "cts_cluster_size": 20,
        "cts_cluster_diameter": 100,
    }
    values = {"core_utilization_pct": list(range(30, 55)), "enable_dpo": [0, 1]}
    recipes = build_orfs_agent_initial_warmup_recipes(
        platform_name="asap7", count=50, seed=401,
        admissible_values=values, fixed_parameters=fixed,
    )
    assert len(recipes) == 50
    assert all(item["parameters"]["core_utilization_pct"] in values["core_utilization_pct"]
               for item in recipes)
    assert all(item["origin"]["domain_kind"] == "target-feasibility-subtractive"
               for item in recipes)
    try:
        build_orfs_agent_initial_warmup_recipes(
            platform_name="asap7", count=50, seed=401,
            admissible_values={"core_utilization_pct": [30, 31]},
            fixed_parameters={**fixed, "enable_dpo": 1},
        )
    except ValueError as error:
        assert "only 2 legal" in str(error)
    else:
        raise AssertionError("insufficient target domain must not loop or duplicate")


def test_orfs_agent_native_execution_rejects_insufficient_observations(tmp_path):
    registry = PluginRegistry.from_directory(ROOT / "integrations/orfs_agent")
    manifest = registry.resolve("orfs-agent", arch=platform.machine())
    task = _task()
    payload = task.to_dict()
    payload["inputs"] = {**payload["inputs"], "mode": "native_agent"}
    execution = ProcessAdapter().execute(manifest, TaskSpec.from_dict(payload), workspace=tmp_path / "attempt")

    assert execution.result.status is RuntimeStatus.FAILED
    assert "at least two measured observations" in execution.result.failure["message"]


def test_orfs_agent_native_path_uses_upstream_gp_ei_with_platform_policy(tmp_path):
    """A symlinked NVM-style launcher remains usable with Runtime's minimal PATH."""
    venv_python = ROOT / ".tools/venvs/orfs-agent/bin/python"
    if not venv_python.is_file():
        raise AssertionError("ORFS-Agent isolated environment is required for this integration test")
    launcher_dir = tmp_path / "nvm" / "bin"
    launcher_dir.mkdir(parents=True)
    node = launcher_dir / "node"
    node.write_text("#!/bin/sh\nexec /usr/bin/python3 \"$@\"\n", encoding="utf-8")
    node.chmod(0o755)
    target = tmp_path / "node_modules" / "codex.js"
    target.parent.mkdir()
    target.write_text(
        "#!/usr/bin/env python3\nimport json,sys\nargs=sys.argv\nout=args[args.index('--output-last-message')+1]\njson.dump({'training_row_ids':[0,1,2],'rationale':'test','uncertainty':'test'},open(out,'w'))\n",
        encoding="utf-8",
    )
    target.chmod(0o755)
    codex = launcher_dir / "codex"
    codex.symlink_to(target)
    observations = []
    for index in range(3):
        observations.append({
            "observation_id": f"run-{index}", "feasible": True,
            "parameters": {
                "clock_period_ns": 1.20 + index * .02, "core_utilization_pct": 40 + index,
                "place_density_lb_addon": .20 + index * .01, "enable_dpo": index % 2,
                "tns_end_percent": 80,
                "global_placement_padding": 1, "detail_placement_padding": 1,
                "cts_cluster_size": 20 + index, "cts_cluster_diameter": 100 + index,
            },
            "metrics": {"setup_wns_ns": -.1 - index * .01, "drc_errors": 0,
                        "wirelength_um": 1000.0 + index, "area_um2": 500.0, "power_mw": 1.0},
        })
    base = orfs_agent_plugin_manifest(ROOT / ".external-src/ORFS-Agent", python_executable=venv_python)
    manifest = replace(base, environment={**base.environment, "ORFS_AGENT_CODEX_EXECUTABLE": str(codex)})
    # The protected production path gives the unchanged upstream workbench an
    # execution domain it can express directly.  This smoke intentionally
    # avoids the historical all-knob nearest-value transport.
    fixed = {
        "tns_end_percent": 80, "global_placement_padding": 1,
        "detail_placement_padding": 1, "enable_dpo": 1,
        "place_density_lb_addon": .20, "cts_cluster_size": 20,
        "cts_cluster_diameter": 100,
    }
    for observation in observations:
        observation["parameters"].update(fixed)
    task = build_orfs_agent_native_task(
        project_id="plugin-test", design_id="ibex", platform_name="asap7",
        objective="ECP_final", observations=observations, n_suggestions=2,
        search_parameter_names=["core_utilization_pct"], fixed_parameters=fixed,
        admissible_values={"core_utilization_pct": [40, 41, 42]},
    )
    execution = ProcessAdapter().execute(
        manifest, task, workspace=tmp_path / "attempt",
        environment={"PATH": "/usr/bin:/bin"},
    )
    assert execution.result.status is RuntimeStatus.SUCCEEDED
    candidates = json.loads((tmp_path / "attempt/orfs_agent_candidates.json").read_text())
    assert len(candidates) == 2
    assert "clock_period_ns" not in candidates[0]["platform_parameters"]
    assert "core_utilization_pct" in candidates[0]["platform_parameters"]
    trace = json.loads((tmp_path / "attempt/orfs_agent_policy_trace.json").read_text())
    assert trace["upstream_algorithm"] == "scikit-optimize GP + EI"
    assert trace["optimizer_seed"] == 1


def test_orfs_agent_native_path_can_use_a_subtractive_target_domain(tmp_path):
    """A target feasibility receipt may fix knobs without replacing GP/EI."""
    venv_python = ROOT / ".tools/venvs/orfs-agent/bin/python"
    codex = tmp_path / "fake-codex"
    codex.write_text(
        "#!/usr/bin/env python3\nimport json,sys\nargs=sys.argv\nout=args[args.index('--output-last-message')+1]\njson.dump({'training_row_ids':[0,1,2],'rationale':'test','uncertainty':'test'},open(out,'w'))\n",
        encoding="utf-8",
    )
    codex.chmod(0o755)
    observations = []
    for index in range(3):
        observations.append({
            "observation_id": f"run-{index}", "feasible": True,
            "parameters": {
                "clock_period_ns": 1.2, "core_utilization_pct": 30 + index,
                "place_density_lb_addon": .20, "enable_dpo": 1,
                "tns_end_percent": 100, "global_placement_padding": 3,
                "detail_placement_padding": 3, "cts_cluster_size": 20,
                "cts_cluster_diameter": 100,
            },
            "metrics": {"setup_wns_ns": -.1 - index * .01, "drc_errors": 0,
                        "wirelength_um": 1000.0 + index, "area_um2": 500.0,
                        "power_mw": 1.0},
        })
    fixed = {
        "tns_end_percent": 100, "global_placement_padding": 3,
        "detail_placement_padding": 3, "enable_dpo": 1,
        "place_density_lb_addon": .20, "cts_cluster_size": 20,
        "cts_cluster_diameter": 100,
    }
    base = orfs_agent_plugin_manifest(ROOT / ".external-src/ORFS-Agent", python_executable=venv_python)
    manifest = replace(base, environment={**base.environment, "ORFS_AGENT_CODEX_EXECUTABLE": str(codex)})
    task = build_orfs_agent_native_task(
        project_id="plugin-test", design_id="aes", platform_name="asap7",
        objective="ECP_final", observations=observations, n_suggestions=2,
        search_parameter_names=["core_utilization_pct"], fixed_parameters=fixed,
        admissible_values={"core_utilization_pct": [30, 31, 32]},
    )
    execution = ProcessAdapter().execute(manifest, task, workspace=tmp_path / "attempt")
    assert execution.result.status is RuntimeStatus.SUCCEEDED
    candidates = json.loads((tmp_path / "attempt/orfs_agent_candidates.json").read_text())
    assert len(candidates) == 2
    assert candidates[0]["platform_parameters"]["tns_end_percent"] == 100
    assert set(candidates[0]["platform_parameters"]) == {
        "core_utilization_pct", *fixed,
    }
    trace = json.loads((tmp_path / "attempt/orfs_agent_policy_trace.json").read_text())
    assert trace["shared_domain"]["search_parameter_names"] == ["core_utilization_pct"]
    assert trace["shared_domain"]["fixed_parameters"] == fixed
    assert trace["shared_domain"]["admissible_values"] == {"core_utilization_pct": [30, 31, 32]}
