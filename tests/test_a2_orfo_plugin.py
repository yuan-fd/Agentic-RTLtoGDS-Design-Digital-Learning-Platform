from __future__ import annotations

import json
from pathlib import Path

import pytest

from openroad_platform_contracts import RuntimeStatus
from openroad_platform_execution import (
    A2_ORFO_PARAMETERS, A2ORFODomain, PluginRegistry,
    a2_orfo_plugin_manifest, build_a2_orfo_initialization_task,
    build_a2_orfo_policy_task,
)
from openroad_platform_scheduler import RuntimeStore, WorkflowRuntime


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "var/external-sources/a2-orfo-8b20a3c-clean"
MODEL = ROOT / "var/external-models/mxbai-embed-large-v1-b33106f"
PYTHON = ROOT / ".tools/venvs/a2-orfo/bin/python"


def _protocol() -> dict:
    return {
        "protocol_id": "a2-orfo-single-feedback-test-v1",
        "a2_orfo_commit": "8b20a3c1f22934a39c7ba51ed0ec6dffe730da2d",
        "orfs_executor_commit": "730f1fa11f9c17c0aaac332412af2b2538f42e9b",
        "design": "aes", "platform": "sky130hd",
        "objective_set": ["ECP", "DWL", "COMBO"],
        "seed_policy": "fixed-test-seed-v1",
        "budget": {"minimum_successful_observations": 4, "feedback_steps": 1},
        "evaluator": "protected-orfs-agent-full-v1",
        "objective_baselines": {"ecp": 4.721, "dwl": 589825.0},
        "design_bundle_sha256": "1" * 64, "pdk_bundle_sha256": "2" * 64,
        "toolchain_receipt_sha256": "3" * 64,
    }


def _domain() -> A2ORFODomain:
    return A2ORFODomain.from_upstream(
        source_root=SOURCE, design="aes", platform_name="sky130hd",
        experiment_protocol=_protocol(),
    )


def _candidate(index: int) -> dict[str, int | float]:
    return {
        "UTIL": 30 + index, "GP_PAD": index % 4, "DP_PAD": (index + 1) % 4,
        "HIER_SYNTH": index % 2, "PIN_ADJ": .25 + index * .02,
        "UP_ADJ": .3 + index * .02, "TNS_End_Percent": 80 + index,
        "LB_ADDON": .1 + index * .02, "CTS_CSIZE": 18 + index,
        "CTS_CDIA": 88 + index, "DPO": index % 2, "CLK": 4.5 + index * .1,
    }


def _observations(count: int = 5) -> list[dict]:
    domain = _domain()
    return [{
        "observation_id": f"protected-{index}", "run_id": f"runtime-{index}",
        "status": "succeeded", "feasible": True,
        "protocol_sha256": domain.protocol_sha256, "candidate": _candidate(index),
        "metrics": {
            "finish__timing__setup__ws": -.2 + index * .04,
            "finish__timing__setup__tns": -2.0 + index * .2,
            "detailedroute__route__wirelength": 590000.0 - index * 1000,
            "detailedroute__route__drc_errors": 0,
            "ECP_final": 4.7 + index * .06,
        },
        "artifact_refs": [f"runtime:runtime-{index}:protected-evaluation"],
    } for index in range(count)]


def _fake_codex(path: Path) -> Path:
    path.write_text(
        """#!/usr/bin/env python3
import json,sys
args=sys.argv
schema=json.load(open(args[args.index('--output-schema')+1]))
out=args[args.index('--output-last-message')+1]
props=schema.get('properties',{})
def value(name, spec):
    if 'enum' in spec: return spec['enum'][0]
    kind=spec.get('type')
    if kind=='integer': return max(spec.get('minimum',0),2 if name=='n_clusters' else 0)
    if kind=='number': return 0.5
    if kind=='boolean': return True
    if kind=='array': return []
    if kind=='object': return {k:value(k,v) for k,v in spec.get('properties',{}).items() if k in spec.get('required',[])}
    if name=='content': return 'Supervisor Feedback: retain evidence, balance exploration, and inspect failures.'
    if name=='reasoning': return 'Measured feedback supports this bounded configuration.'
    return 'bounded'
result={name:value(name,props[name]) for name in schema.get('required',[])}
json.dump(result,open(out,'w'))
""", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_a2_domain_and_task_preserve_native_twelve_dimensions():
    domain = _domain()
    task = build_a2_orfo_policy_task(
        project_id="a2-test", design_id="aes", objective="ECP",
        observations=_observations(), domain=domain, n_suggestions=1,
        optimizer_seed=41, task_id="a2-policy-test",
    )
    assert tuple(task.inputs["parameter_domain"]["parameter_names"]) == A2_ORFO_PARAMETERS
    assert task.plugin_id == "a2-orfo"
    assert task.labels["optimizer_origin"].startswith("external:A2-ORFO@")
    with pytest.raises(ValueError, match="at least 4"):
        build_a2_orfo_policy_task(
            project_id="a2-test", design_id="aes", objective="ECP",
            observations=_observations(3), domain=domain, n_suggestions=1,
            optimizer_seed=41,
        )


def test_native_a2_initializer_task_needs_no_historical_observations():
    task = build_a2_orfo_initialization_task(
        project_id="a2-test", design_id="aes", objective="ECP",
        domain=_domain(), count=4, optimizer_seed=37,
        task_id="a2-initializer-test")
    assert task.inputs["mode"] == "native_initialize"
    assert task.inputs["observations"] == []
    assert task.inputs["n_suggestions"] == 4
    assert task.labels["upstream_entrypoint"].endswith("generate_initial_parameters")


def test_a2_policy_accepts_pinned_launcher_parallel_runs():
    task = build_a2_orfo_policy_task(
        project_id="a2-test", design_id="aes", objective="ECP",
        observations=_observations(), domain=_domain(), n_suggestions=25,
        optimizer_seed=17,
    )
    assert task.inputs["n_suggestions"] == 25


def test_a2_manifest_rejects_dirty_or_unpinned_source(tmp_path):
    fake = _fake_codex(tmp_path / "codex")
    manifest = a2_orfo_plugin_manifest(
        SOURCE, model_root=MODEL, python_executable=PYTHON, codex_executable=fake)
    assert "optimizer.l2.a2-orfo-policy" in manifest.capabilities
    assert manifest.plugin_id == "a2-orfo"


def test_native_a2_workflow_runs_inside_runtime_with_structured_provider(tmp_path):
    fake = _fake_codex(tmp_path / "codex")
    manifest = a2_orfo_plugin_manifest(
        SOURCE, model_root=MODEL, python_executable=PYTHON,
        codex_executable=fake, default_timeout_seconds=600)
    runtime = WorkflowRuntime(
        RuntimeStore(tmp_path / "runtime.sqlite"), PluginRegistry([manifest]),
        workspace_root=tmp_path / "work", worker_id="a2-test-worker",
    )
    task = build_a2_orfo_policy_task(
        project_id="a2-test", design_id="aes", objective="ECP",
        observations=_observations(), domain=_domain(), n_suggestions=1,
        optimizer_seed=41, task_id="a2-native-policy-test", timeout_seconds=600,
    )
    run = runtime.submit(task, capability="optimizer.l2.a2-orfo-policy")
    finished = runtime.execute_once(run.run_id)
    if finished.status is not RuntimeStatus.SUCCEEDED:
        result_path = next((tmp_path / "work").rglob("adapter_result.json"))
        raise AssertionError(result_path.read_text())
    candidates = json.loads(next((tmp_path / "work").rglob("a2_candidates.json")).read_text())
    assert len(candidates) == 1
    assert tuple(candidates[0]) == A2_ORFO_PARAMETERS
    trace = json.loads(next((tmp_path / "work").rglob("model_provider_trace.json")).read_text())
    assert trace["calls"]
    assert all(call["executed_model"] == "gpt-5.6-terra" for call in trace["calls"])
    stage_tools = [call.get("function_name") for call in trace["calls"][:3]]
    assert stage_tools[:2] == ["configure_inspection", "configure_model"]
    assert stage_tools[2] == "configure_model"  # first ReAct GPR feedback action
    assert "configure_selection" in [call.get("function_name") for call in trace["calls"]]
    retrieval = json.loads(next((tmp_path / "work").rglob("a2_knowledge_retrieval.json")).read_text())
    assert retrieval["corpus_documents"] == 580
    assert retrieval["embedding_dimension"] == 1024
    view = runtime.describe(run.run_id)
    kinds = {artifact["kind"] for stage in view["stages"] for attempt in stage["attempts"]
             for artifact in attempt["artifacts"]}
    assert {"optimizer_candidates", "optimizer_checkpoint", "knowledge_retrieval",
            "model_provider_trace", "runtime_protocol_receipt"} <= kinds


def test_native_a2_initializer_runs_upstream_inside_runtime(tmp_path):
    fake = _fake_codex(tmp_path / "codex")
    manifest = a2_orfo_plugin_manifest(
        SOURCE, model_root=MODEL, python_executable=PYTHON,
        codex_executable=fake, default_timeout_seconds=600)
    runtime = WorkflowRuntime(
        RuntimeStore(tmp_path / "runtime.sqlite"), PluginRegistry([manifest]),
        workspace_root=tmp_path / "work", worker_id="a2-initializer-worker")
    task = build_a2_orfo_initialization_task(
        project_id="a2-test", design_id="aes", objective="ECP",
        domain=_domain(), count=4, optimizer_seed=37,
        task_id="a2-native-initializer", timeout_seconds=600)
    run = runtime.submit(task, capability="optimizer.l2.a2-orfo-initialize")
    finished = runtime.execute_once(run.run_id)
    if finished.status is not RuntimeStatus.SUCCEEDED:
        result_path = next((tmp_path / "work").rglob("adapter_result.json"))
        raise AssertionError(result_path.read_text())
    candidates = json.loads(next(
        (tmp_path / "work").rglob("a2_candidates.json")).read_text())
    assert len(candidates) == 4
    assert all(tuple(candidate) == A2_ORFO_PARAMETERS for candidate in candidates)
    trace = json.loads(next((tmp_path / "work").rglob("a2_policy_trace.json")).read_text())
    assert trace["entrypoint"] == "OptimizationWorkflow.generate_initial_parameters"
    provider = json.loads(next(
        (tmp_path / "work").rglob("model_provider_trace.json")).read_text())
    assert provider["calls"] == []
    view = runtime.describe(run.run_id)
    kinds = {artifact["kind"] for stage in view["stages"] for attempt in stage["attempts"]
             for artifact in attempt["artifacts"]}
    assert {"optimizer_candidates", "optimizer_checkpoint", "knowledge_retrieval",
            "model_provider_trace", "runtime_protocol_receipt"} <= kinds
