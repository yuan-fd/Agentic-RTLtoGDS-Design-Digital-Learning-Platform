from __future__ import annotations

import json
import hashlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from openroad_platform_contracts import RuntimeStatus
from openroad_platform_execution import (
    ORFSAgentFullDomain,
    PluginRegistry,
    build_orfs_agent_full_candidate_task,
    build_orfs_agent_full_initialization_task,
    build_orfs_agent_full_policy_task,
    orfs_agent_full_protocol_receipts,
    orfs_agent_plugin_manifest,
)
from openroad_platform_scheduler import RuntimeStore, WorkflowRuntime


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "var/external-sources/orfs-agent-730f1fa-clean-20260901"
PARAMETERS = (
    "CLK", "UTIL", "TNS_End_Percent", "GP_PAD", "DP_PAD", "DPO",
    "PIN_ADJ", "UP_ADJ", "LB_ADDON", "HIER_SYNTH", "CTS_CSIZE", "CTS_CDIA",
)


def _protocol() -> dict:
    return {
        "protocol_id": "orfs-agent-upstream-full-v1",
        "orfs_agent_commit": "730f1fa11f9c17c0aaac332412af2b2538f42e9b",
        "orfs_commit": "ce8d36a7fef0ab9c47d183bcf078bce0f60f5a54",
        "design": "aes",
        "platform": "sky130hd",
        "objective_set": ["ECP", "DWL", "COMBO"],
        "seed_policy": "frozen-upstream-initialization-and-per-round-gp-seed-v1",
        "budget": {"initial_samples": 50, "rounds": 5,
                   "suggestions_per_round": 5, "confirmations": 3},
        "evaluator": "protected-orfs-agent-full-v1",
        "initialization_method": "upstream:OptimizationWorkflow.generate_initial_parameters",
        "design_bundle_sha256": "1" * 64,
        "pdk_bundle_sha256": "2" * 64,
        "toolchain_receipt_sha256": "3" * 64,
    }


def _candidate(index: int = 0) -> dict[str, float | int]:
    return {
        "CLK": 4.5 + index * .1,
        "UTIL": 20 + index,
        "TNS_End_Percent": 100,
        "GP_PAD": index % 4,
        "DP_PAD": (index + 1) % 4,
        "DPO": index % 2,
        "PIN_ADJ": .3,
        "UP_ADJ": .4,
        "LB_ADDON": .2 + index * .01,
        "HIER_SYNTH": index % 2,
        "CTS_CSIZE": 10 + index,
        "CTS_CDIA": 80 + index,
    }


def _domain() -> ORFSAgentFullDomain:
    return ORFSAgentFullDomain.from_upstream(
        source_root=SOURCE, design="aes", platform="sky130hd",
        experiment_protocol=_protocol(),
    )


def _observations(domain: ORFSAgentFullDomain) -> list[dict]:
    return [
        {
            "observation_id": f"measured-{index}",
            "protocol_sha256": domain.protocol_sha256,
            "candidate": _candidate(index),
            "metrics": {
                "finish__timing__setup__ws": -.2 - index * .01,
                "detailedroute__route__wirelength": 589825.0 + index * 1000,
                "detailedroute__route__drc_errors": 0,
            },
            "artifact_refs": [f"artifact:runtime:measured-{index}:qor"],
        }
        for index in range(3)
    ]


def test_full_domain_preserves_every_upstream_parameter_and_objective() -> None:
    domain = _domain()
    payload = domain.to_dict()
    assert payload["kind"] == "upstream-full-12d"
    assert tuple(payload["parameter_names"]) == PARAMETERS
    assert payload["variable_clock_semantics"] is True
    assert payload["experiment_protocol"]["objective_set"] == ["ECP", "DWL", "COMBO"]
    assert ORFSAgentFullDomain.from_dict(payload).to_dict() == payload


def test_full_domain_allows_upstream_protocol_without_confirmations() -> None:
    protocol = _protocol()
    protocol["budget"]["confirmations"] = 0
    domain = ORFSAgentFullDomain.from_upstream(
        source_root=SOURCE, design="aes", platform="sky130hd",
        experiment_protocol=protocol)
    assert domain.experiment_protocol["budget"]["confirmations"] == 0


def test_full_domain_rejects_reduced_candidate_and_protocol_drift() -> None:
    domain = _domain()
    reduced = _candidate(); reduced.pop("CLK")
    with pytest.raises(ValueError, match="all 12"):
        domain.validate_candidate(reduced)
    observation = _observations(domain)[0]
    observation["protocol_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="protocol"):
        domain.validate_observation(observation)


def test_full_policy_task_keeps_domain_and_never_projects_platform_parameters() -> None:
    domain = _domain()
    task = build_orfs_agent_full_policy_task(
        project_id="full", design_id="aes", objective="ECP",
        observations=_observations(domain), domain=domain,
        n_suggestions=2, optimizer_seed=17,
    )
    assert task.plugin_id == "orfs-agent"
    assert task.inputs["mode"] == "upstream_full_policy"
    assert tuple(task.inputs["parameter_domain"]["parameter_names"]) == PARAMETERS
    assert "platform_parameters" not in json.dumps(task.to_dict())


def test_full_candidate_task_keeps_all_12_fields_and_runtime_seed() -> None:
    domain = _domain()
    candidate = _candidate()
    task = build_orfs_agent_full_candidate_task(
        project_id="full", design_id="aes", objective="ECP", domain=domain,
        candidate=candidate, or_seed=101, task_id="full-candidate-101",
    )
    assert task.plugin_id == "orfs-agent"
    assert task.inputs["mode"] == "upstream_full_candidate"
    assert {"odb", "def", "netlist", "sdc", "spef"} <= set(
        task.expected_artifacts)
    assert tuple(task.inputs["candidate"]) == PARAMETERS
    assert task.inputs["candidate"] == candidate
    assert task.parameters["or_seed"] == 101
    assert "platform_parameters" not in json.dumps(task.to_dict())


def test_full_candidate_runtime_preserves_typed_task_without_projection(tmp_path: Path) -> None:
    class _CandidateAdapter:
        def execute(self, manifest, task, *, workspace, **_kwargs):
            assert manifest.plugin_id == task.plugin_id == "orfs-agent"
            assert tuple(task.inputs["candidate"]) == PARAMETERS
            assert task.parameters["or_seed"] == 307
            root = Path(workspace); root.mkdir(parents=True, exist_ok=True)
            artifacts = []
            for index, kind in enumerate(task.expected_artifacts):
                path = root / f"artifact-{index}.json"
                path.write_text(json.dumps({"candidate": task.inputs["candidate"]}))
                artifacts.append({
                    "kind": kind, "store_key": path.name,
                    "size_bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "metadata": {},
                })
            result = SimpleNamespace(
                status=RuntimeStatus.SUCCEEDED, exit_code=0, metrics=(), failure=None,
            )
            return SimpleNamespace(result=result, artifacts=tuple(artifacts))

        def validate_additional_artifacts(self, workspace, _manifest, artifacts):
            root = Path(workspace)
            normalized = []
            for item in artifacts:
                path = root / item["path"]
                normalized.append({
                    "kind": item["kind"], "store_key": item["path"],
                    "size_bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "metadata": dict(item.get("metadata") or {}),
                })
            return tuple(normalized)

    domain = _domain()
    task = build_orfs_agent_full_candidate_task(
        project_id="full", design_id="aes", objective="ECP", domain=domain,
        candidate=_candidate(1), or_seed=307, task_id="full-candidate-runtime",
    )
    runtime = WorkflowRuntime(
        RuntimeStore(tmp_path / "runtime.sqlite"),
        PluginRegistry([orfs_agent_plugin_manifest(SOURCE)]),
        workspace_root=tmp_path / "work", adapter=_CandidateAdapter(),
    )
    run = runtime.submit(task, capability="optimizer.l2.upstream-full-12d")
    assert runtime.execute_once(run.run_id).status is RuntimeStatus.SUCCEEDED
    stored = runtime.store.get_run(run.run_id).task_spec
    assert stored.to_dict() == task.to_dict()


def test_manifest_rejects_audit_cache_and_accepts_clean_detached_source() -> None:
    with pytest.raises(ValueError, match="source-audit cache"):
        orfs_agent_plugin_manifest(
            ROOT / ".external-src/orfs-agent-admission-20260830-vNWf4x/ORFS-Agent")
    manifest = orfs_agent_plugin_manifest(SOURCE)
    assert "optimizer.l2.upstream-full-12d" in manifest.capabilities
    assert "optimizer.l2.upstream-full-candidate" not in manifest.capabilities


def test_full_candidate_capability_requires_complete_pinned_paper_toolchain() -> None:
    with pytest.raises(ValueError, match="configured together"):
        orfs_agent_plugin_manifest(SOURCE, paper_orfs_root="/tmp/incomplete")
    paper = Path("/tmp/orfs-agent-paper-orfs-clean")
    openroad = ROOT / "var/toolchains/orfs-ce8d36a-paper-install-boost180-headless-fmtranges-include-20260903/OpenROAD/bin/openroad"
    yosys = ROOT / "var/toolchains/orfs-ce8d36a-paper-install-boost180-20260902/yosys/bin/yosys"
    if not all(path.exists() for path in (paper, openroad, yosys)):
        pytest.fail("admitted paper ORFS/OpenROAD/Yosys toolchain is required")
    manifest = orfs_agent_plugin_manifest(
        SOURCE, paper_orfs_root=paper, openroad_bin=openroad, yosys_bin=yosys,
        paper_runtime_environment={"LD_LIBRARY_PATH": "/audited/toolchain/libs"},
    )
    assert "optimizer.l2.upstream-full-candidate" in manifest.capabilities
    assert manifest.environment["OPENROAD_BIN"] == str(openroad.resolve())
    assert manifest.environment["YOSYS_BIN"] == str(yosys.resolve())
    assert str(openroad.parent.resolve()) in manifest.environment["PATH"].split(":")
    assert str(yosys.parent.resolve()) in manifest.environment["PATH"].split(":")
    assert manifest.environment["LD_LIBRARY_PATH"] == "/audited/toolchain/libs"
    receipts = orfs_agent_full_protocol_receipts(
        source_root=SOURCE, paper_orfs_root=paper,
        openroad_bin=openroad, yosys_bin=yosys, design="aes",
        platform_name="sky130hd",
        paper_runtime_environment={"LD_LIBRARY_PATH": "/audited/toolchain/libs"},
    )
    assert len(receipts["design_bundle_sha256"]) == 64
    assert len(receipts["pdk_bundle_sha256"]) == 64
    assert len(receipts["toolchain_receipt_sha256"]) == 64
    admitted = json.loads(manifest.environment["ORFS_AGENT_PAPER_RECEIPTS_JSON"])
    assert admitted["inputs"]["sky130hd/aes"]["design_bundle_sha256"] == (
        receipts["design_bundle_sha256"])
    assert admitted["toolchain_receipt_sha256"] == receipts["toolchain_receipt_sha256"]


def test_full_policy_runs_upstream_gp_ei_through_runtime(tmp_path: Path) -> None:
    python = ROOT / ".tools/venvs/orfs-agent/bin/python"
    if not python.is_file():
        pytest.fail("admitted ORFS-Agent virtualenv is required")
    fake_codex = tmp_path / "codex"
    fake_codex.write_text(
        "#!/usr/bin/env python3\n"
        "import json,sys\n"
        "out=sys.argv[sys.argv.index('--output-last-message')+1]\n"
        "json.dump({'training_row_ids':[0,1,2],'rationale':'measured rows','uncertainty':'test'},open(out,'w'))\n",
        encoding="utf-8",
    )
    fake_codex.chmod(0o755)
    manifest = orfs_agent_plugin_manifest(SOURCE, python_executable=python)
    manifest = replace(manifest, environment={**manifest.environment,
                                              "ORFS_AGENT_CODEX_EXECUTABLE": str(fake_codex)})
    domain = _domain()
    task = build_orfs_agent_full_policy_task(
        project_id="full", design_id="aes", objective="ECP",
        observations=_observations(domain), domain=domain,
        n_suggestions=2, optimizer_seed=17,
    )
    runtime = WorkflowRuntime(
        RuntimeStore(tmp_path / "runtime.sqlite"), PluginRegistry([manifest]),
        workspace_root=tmp_path / "work",
    )
    run = runtime.submit(task)
    finished = runtime.execute_once(run.run_id)
    assert finished.status is RuntimeStatus.SUCCEEDED
    candidates = json.loads(next((tmp_path / "work").rglob("paper_candidates.json")).read_text())
    assert len(candidates) == 2
    assert all(set(candidate) == set(PARAMETERS) for candidate in candidates)


def test_full_initialization_runs_pinned_upstream_initializer_through_runtime(tmp_path: Path) -> None:
    python = ROOT / ".tools/venvs/orfs-agent/bin/python"
    manifest = orfs_agent_plugin_manifest(SOURCE, python_executable=python)
    domain = _domain()
    task = build_orfs_agent_full_initialization_task(
        project_id="full", design_id="aes", objective="ECP", domain=domain,
        count=4, initialization_seed=23,
    )
    runtime = WorkflowRuntime(
        RuntimeStore(tmp_path / "runtime.sqlite"), PluginRegistry([manifest]),
        workspace_root=tmp_path / "work",
    )
    run = runtime.submit(task)
    assert runtime.execute_once(run.run_id).status is RuntimeStatus.SUCCEEDED
    candidates = json.loads(next((tmp_path / "work").rglob("initial_candidates.json")).read_text())
    trace = json.loads(next((tmp_path / "work").rglob("initialization_trace.json")).read_text())
    assert len(candidates) == 4
    assert all(tuple(candidate) == PARAMETERS for candidate in candidates)
    assert trace["entrypoint"] == "OptimizationWorkflow.generate_initial_parameters"
    assert trace["seed"] == 23
