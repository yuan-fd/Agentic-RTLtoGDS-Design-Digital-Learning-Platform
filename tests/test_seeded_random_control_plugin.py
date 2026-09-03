from __future__ import annotations

import json
import subprocess
from pathlib import Path

from openroad_platform_execution import (
    PluginRegistry, build_seeded_random_control_task, seeded_random_control_plugin_manifest,
)
from openroad_platform_scheduler import RuntimeStore, WorkflowRuntime


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".tools/venvs/seeded-random-control/bin/python"
ADAPTER = ROOT / "integrations/seeded_random_control/seeded_random_control_adapter.py"


def _domain() -> tuple[list[str], dict, dict]:
    names = ["core_utilization_pct", "tns_end_percent"]
    fixed = {
        "global_placement_padding": 1,
        "detail_placement_padding": 1,
        "enable_dpo": 1,
        "place_density_lb_addon": .2,
        "cts_cluster_size": 20,
        "cts_cluster_diameter": 90,
    }
    values = {"core_utilization_pct": [30, 31], "tns_end_percent": [80, 90]}
    return names, fixed, values


def test_control_task_is_typed_and_binds_the_complete_shared_domain():
    names, fixed, values = _domain()
    task = build_seeded_random_control_task(
        project_id="study", design_id="aes", platform_name="sky130hd", objective="balanced",
        search_parameter_names=names, fixed_parameters=fixed, admissible_values=values,
        excluded_parameters=[], n_suggestions=2, seed=17,
    )
    assert task.plugin_id == "seeded-random-control"
    assert task.inputs["seed"] == 17
    assert task.inputs["excluded_parameter_fingerprints"] == []
    assert set(task.inputs["fixed_parameters"]) | set(task.inputs["search_parameter_names"]) == {
        "core_utilization_pct", "tns_end_percent", "global_placement_padding",
        "detail_placement_padding", "enable_dpo", "place_density_lb_addon",
        "cts_cluster_size", "cts_cluster_diameter",
    }
    manifest = seeded_random_control_plugin_manifest(python_executable=PYTHON)
    assert manifest.plugin_id == task.plugin_id
    assert manifest.capabilities == ("optimizer.l2.control.random",)


def test_control_adapter_is_deterministic_without_qor_access_or_replacement(tmp_path: Path):
    names, fixed, values = _domain()
    excluded = [{**fixed, "core_utilization_pct": 30, "tns_end_percent": 80}]
    task = build_seeded_random_control_task(
        project_id="study", design_id="aes", platform_name="sky130hd", objective="balanced",
        search_parameter_names=names, fixed_parameters=fixed, admissible_values=values,
        excluded_parameters=excluded, n_suggestions=2, seed=23,
    )
    request, result = tmp_path / "request.json", tmp_path / "result.json"
    request.write_text(json.dumps({"task": task.to_dict()}), encoding="utf-8")
    completed = subprocess.run(
        [str(PYTHON), str(ADAPTER), "--request", str(request), "--result", str(result)],
        text=True, capture_output=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["status"] == "succeeded"
    assert payload["provenance"]["qor_access"] is False
    candidates = json.loads((tmp_path / "optimizer_candidates.json").read_text(encoding="utf-8"))["candidates"]
    assert len(candidates) == 2
    assert len({json.dumps(row["platform_parameters"], sort_keys=True) for row in candidates}) == 2
    assert all(row["sampling"]["algorithm"] == "uniform_without_replacement_over_finite_admitted_domain"
               for row in candidates)


def test_control_adapter_refuses_to_fill_a_batch_by_repeating_coordinates(tmp_path: Path):
    names, fixed, values = _domain()
    excluded = [
        {**fixed, "core_utilization_pct": 30, "tns_end_percent": 80},
        {**fixed, "core_utilization_pct": 30, "tns_end_percent": 90},
        {**fixed, "core_utilization_pct": 31, "tns_end_percent": 80},
    ]
    task = build_seeded_random_control_task(
        project_id="study", design_id="aes", platform_name="sky130hd", objective="balanced",
        search_parameter_names=names, fixed_parameters=fixed, admissible_values=values,
        excluded_parameters=excluded, n_suggestions=2, seed=29,
    )
    request, result = tmp_path / "request.json", tmp_path / "result.json"
    request.write_text(json.dumps({"task": task.to_dict()}), encoding="utf-8")
    completed = subprocess.run(
        [str(PYTHON), str(ADAPTER), "--request", str(request), "--result", str(result)],
        text=True, capture_output=True, check=False,
    )
    assert completed.returncode == 1
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert "no replacement" in payload["failure"]["message"]


def test_control_plugin_completes_a_bounded_runtime_attempt(tmp_path: Path):
    names, fixed, values = _domain()
    task = build_seeded_random_control_task(
        project_id="study", design_id="aes", platform_name="sky130hd", objective="balanced",
        search_parameter_names=names, fixed_parameters=fixed, admissible_values=values,
        excluded_parameters=[], n_suggestions=2, seed=31,
    )
    runtime = WorkflowRuntime(
        RuntimeStore(tmp_path / "runtime.db"),
        PluginRegistry([seeded_random_control_plugin_manifest(python_executable=PYTHON)]),
        workspace_root=tmp_path / "attempts", worker_id="control-plugin-test",
    )
    run = runtime.submit(task)
    completed = runtime.execute_once(run.run_id)
    assert completed.status.value == "succeeded"
    artifacts = [item for stage in runtime.store.describe_run(run.run_id)["stages"]
                 for attempt in stage["attempts"] for item in attempt["artifacts"]]
    assert {item["kind"] for item in artifacts} == {
        "optimizer_candidates", "optimizer_input_manifest", "optimizer_trace",
    }
