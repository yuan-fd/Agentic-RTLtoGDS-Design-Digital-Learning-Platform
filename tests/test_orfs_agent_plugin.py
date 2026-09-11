from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from openroad_platform_contracts.platform import RuntimeStatus, TaskSpec
from openroad_platform_execution.registry import PluginRegistry
from openroad_platform_execution.orfs_agent_plugin import (
    build_orfs_agent_initial_warmup_recipes, orfs_agent_plugin_manifest,
)
from openroad_platform_execution.orfs_agent_domain import ORFSAgentDomain
from openroad_platform_execution.orfs_agent_task import (
    build_orfs_agent_dataset_task, build_orfs_agent_native_task,
)
from openroad_platform_execution.orfs_agent_plugin import _managed_codex_executable
from openroad_platform_scheduler import RuntimeStore, WorkflowRuntime
from scripts.run_orfs_agent_paper_campaign import (
    FORMAL_STAGE_TIMEOUT_SECONDS,
    _admitted_domain_capacity,
    build_argument_parser,
)


ROOT = Path(__file__).parents[1]
EXECUTION_SOURCE = ROOT / "var/external-sources/orfs-agent-730f1fa-clean-20260901"


def _protocol(clock: float = 1.2) -> dict:
    return {
        "rtl_sha256": "a" * 64, "pdk_id": "asap7",
        "toolchain_id": "openroad-26Q1", "sdc_sha256": "b" * 64,
        "evaluator_version": "orfs-protected-v1", "seed_policy": "fixed-v1",
        "timing": {"clock_period_ns": clock, "clock_uncertainty_ns": .1,
                   "io_delay_ns": .2},
    }


def _shared_domain(*, clock: float = 1.2, values=(40, 41, 42), fixed=None) -> ORFSAgentDomain:
    fixed_values = fixed or {
        "tns_end_percent": 80, "global_placement_padding": 1,
        "detail_placement_padding": 1, "enable_dpo": 1,
        "place_density_lb_addon": .2, "cts_cluster_size": 20,
        "cts_cluster_diameter": 100,
    }
    return ORFSAgentDomain.create(
        platform="asap7", search_parameter_names=("core_utilization_pct",),
        admissible_values={"core_utilization_pct": values},
        fixed_parameters=fixed_values, experiment_protocol=_protocol(clock),
    )


def _shared_observation(index: int = 0, *, domain: ORFSAgentDomain | None = None) -> dict:
    domain = domain or _shared_domain()
    parameters = {"clock_period_ns": domain.experiment_protocol["timing"]["clock_period_ns"],
                  **domain.fixed_parameters,
                  "core_utilization_pct": domain.admissible_values["core_utilization_pct"][index]}
    return {
        "observation_id": f"run-{index}", "feasible": True,
        "protocol_sha256": domain.to_dict()["protocol_sha256"],
        "artifact_refs": [f"runtime:run-{index}:report"], "parameters": parameters,
        "metrics": {"setup_wns_ns": -.1 - index * .01, "setup_tns_ns": -1.2,
                    "drc_errors": 0, "wirelength_um": 115285.0 + index,
                    "area_um2": 1200.0, "power_mw": 10.0,
                    "optimizer_objective": 1.3 + index * .01},
    }


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
    domain = _shared_domain()
    return build_orfs_agent_dataset_task(
        project_id="plugin-test", design_id="ibex", objective="ECP_final",
        observations=[_shared_observation(domain=domain)], domain=domain,
        task_id="orfs-agent-bridge", timeout_seconds=30,
    )


def test_orfs_agent_bridge_materializes_pinned_upstream_dataset(tmp_path):
    manifest = orfs_agent_plugin_manifest(EXECUTION_SOURCE)
    runtime = WorkflowRuntime(RuntimeStore(tmp_path / "runtime.sqlite"),
                              PluginRegistry([manifest]), workspace_root=tmp_path / "work")
    run = runtime.submit(_task())
    finished = runtime.execute_once(run.run_id)
    assert finished.status is RuntimeStatus.SUCCEEDED
    view = runtime.describe(run.run_id)
    kinds = {item["kind"] for stage in view["stages"] for attempt in stage["attempts"]
             for item in attempt["artifacts"]}
    assert kinds == {"optimizer_dataset", "optimizer_input_manifest", "upstream_source_lock",
                     "runtime_protocol_receipt"}
    dataset = json.loads(next((tmp_path / "work").rglob("orfs_agent_output.json")).read_text())
    assert dataset[0]["circuit"] == "ibex"
    assert dataset[0]["pdk"] == "asap7"
    assert dataset[0]["ECP_final"] == 1.3
    assert dataset[0]["platform_observation_id"] == "run-0"
    manifest_data = json.loads(next((tmp_path / "work").rglob("orfs_agent_input_manifest.json")).read_text())
    assert manifest_data["upstream"]["commit"] == "730f1fa11f9c17c0aaac332412af2b2538f42e9b"


def test_orfs_agent_platform_task_builder_and_manifest_do_not_import_an_optimizer():
    domain = _shared_domain()
    task = build_orfs_agent_dataset_task(
        project_id="plugin-test", design_id="ibex", objective="ECP_final",
        observations=[_shared_observation(domain=domain)], domain=domain,
    )
    manifest = orfs_agent_plugin_manifest(EXECUTION_SOURCE)
    assert task.plugin_id == "orfs-agent"
    assert task.inputs["mode"] == "materialize_dataset"
    assert "optimizer.l2.propose" in manifest.capabilities
    assert manifest.environment["ORFS_AGENT_EXPECTED_COMMIT"] == "730f1fa11f9c17c0aaac332412af2b2538f42e9b"


def test_orfs_agent_native_task_builder_only_adds_bounded_invocation_fields():
    domain = _shared_domain()
    task = build_orfs_agent_native_task(
        project_id="plugin-test", design_id="ibex", objective="ECP_final",
        observations=[_shared_observation(domain=domain)], domain=domain,
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
    domain = _shared_domain()
    task = build_orfs_agent_native_task(
        project_id="plugin-test", design_id="ibex", objective="ECP_final",
        observations=[_shared_observation(domain=domain)], domain=domain,
        n_suggestions=2, optimizer_seed=1,
    )
    manifest = orfs_agent_plugin_manifest(EXECUTION_SOURCE)
    runtime = WorkflowRuntime(RuntimeStore(tmp_path / "runtime.sqlite"),
                              PluginRegistry([manifest]), workspace_root=tmp_path / "work")
    run = runtime.submit(task); finished = runtime.execute_once(run.run_id)
    assert finished.status is RuntimeStatus.FAILED
    result = json.loads(next((tmp_path / "work").rglob("adapter_result.json")).read_text())
    assert "at least two observations" in result["failure"]["message"]


def test_historical_eight_dimensional_native_path_fails_closed_on_upstream_domain_mismatch(tmp_path):
    """The legacy fixed-clock projection must not masquerade as full upstream GP/EI."""
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
    fixed = {
        "tns_end_percent": 80, "global_placement_padding": 1,
        "detail_placement_padding": 1, "enable_dpo": 1,
        "place_density_lb_addon": .20, "cts_cluster_size": 20,
        "cts_cluster_diameter": 100,
    }
    domain = _shared_domain(fixed=fixed)
    observations = [_shared_observation(index, domain=domain) for index in range(3)]
    base = orfs_agent_plugin_manifest(EXECUTION_SOURCE, python_executable=venv_python)
    manifest = replace(base, environment={**base.environment, "ORFS_AGENT_CODEX_EXECUTABLE": str(codex)})
    # The protected production path gives the unchanged upstream workbench an
    # execution domain it can express directly.  This smoke intentionally
    # avoids the historical all-knob nearest-value transport.
    task = build_orfs_agent_native_task(
        project_id="plugin-test", design_id="ibex", objective="ECP_final",
        observations=observations, domain=domain, n_suggestions=2, optimizer_seed=1,
    )
    runtime = WorkflowRuntime(RuntimeStore(tmp_path / "runtime.sqlite"),
                              PluginRegistry([manifest]), workspace_root=tmp_path / "work")
    run = runtime.submit(task); finished = runtime.execute_once(run.run_id)
    assert finished.status is RuntimeStatus.FAILED
    result = json.loads(next((tmp_path / "work").rglob("adapter_result.json")).read_text())
    assert "Not all points are within the bounds" in result["failure"]["message"]


def test_historical_subtractive_native_domain_fails_closed_instead_of_snapping(tmp_path):
    """A reduced domain cannot be made valid by silently snapping upstream proposals."""
    venv_python = ROOT / ".tools/venvs/orfs-agent/bin/python"
    codex = tmp_path / "fake-codex"
    codex.write_text(
        "#!/usr/bin/env python3\nimport json,sys\nargs=sys.argv\nout=args[args.index('--output-last-message')+1]\njson.dump({'training_row_ids':[0,1,2],'rationale':'test','uncertainty':'test'},open(out,'w'))\n",
        encoding="utf-8",
    )
    codex.chmod(0o755)
    fixed = {
        "tns_end_percent": 100, "global_placement_padding": 3,
        "detail_placement_padding": 3, "enable_dpo": 1,
        "place_density_lb_addon": .20, "cts_cluster_size": 20,
        "cts_cluster_diameter": 100,
    }
    domain = _shared_domain(values=(30, 31, 32), fixed=fixed)
    observations = [_shared_observation(index, domain=domain) for index in range(3)]
    base = orfs_agent_plugin_manifest(EXECUTION_SOURCE, python_executable=venv_python)
    manifest = replace(base, environment={**base.environment, "ORFS_AGENT_CODEX_EXECUTABLE": str(codex)})
    task = build_orfs_agent_native_task(
        project_id="plugin-test", design_id="aes", objective="ECP_final",
        observations=observations, domain=domain, n_suggestions=2, optimizer_seed=1,
    )
    runtime = WorkflowRuntime(RuntimeStore(tmp_path / "runtime.sqlite"),
                              PluginRegistry([manifest]), workspace_root=tmp_path / "work")
    run = runtime.submit(task); finished = runtime.execute_once(run.run_id)
    assert finished.status is RuntimeStatus.FAILED
    result = json.loads(next((tmp_path / "work").rglob("adapter_result.json")).read_text())
    assert "Not all points are within the bounds" in result["failure"]["message"]
