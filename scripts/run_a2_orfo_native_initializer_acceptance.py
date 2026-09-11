#!/usr/bin/env python3
"""Execute the pinned upstream A2-ORFO native initializer in Runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
for source_root in (ROOT, *(ROOT / "packages" / name / "src" for name in
                            ("contracts", "analysis", "scheduler", "execution"))):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from openroad_platform_contracts import RuntimeStatus  # noqa: E402
from openroad_platform_execution import (  # noqa: E402
    A2_ORFO_PARAMETERS, A2ORFODomain, PluginRegistry, a2_orfo_plugin_manifest,
    build_a2_orfo_initialization_task,
)
from openroad_platform_scheduler import RuntimeStore, WorkflowRuntime  # noqa: E402


SOURCE = ROOT / "var/external-sources/a2-orfo-8b20a3c-clean"
MODEL = ROOT / "var/external-models/mxbai-embed-large-v1-b33106f"
PYTHON = ROOT / ".tools/venvs/a2-orfo/bin/python"
CODEX = Path("/share/home/yuanwenjie/.nvm/versions/node/v24.18.0/bin/codex")
LOCK = ROOT / "integrations/a2_orfo/source.lock.json"
LOCK_SHA = "635582cb7faceb852b342f6bb8697bcef290c8f7cb1eed62bb87fbce775ed81a"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _protocol():
    return {
        "protocol_id": "a2-orfo-native-bootstrap-aes-sky130hd-v1",
        "a2_orfo_commit": "8b20a3c1f22934a39c7ba51ed0ec6dffe730da2d",
        "orfs_executor_commit": "730f1fa11f9c17c0aaac332412af2b2538f42e9b",
        "design": "aes", "platform": "sky130hd",
        "objective_set": ["ECP", "DWL", "COMBO"],
        "seed_policy": "a2-native-initializer-37",
        "budget": {"minimum_successful_observations": 4, "feedback_steps": 1},
        "evaluator": "protected-orfs-agent-full-v1",
        "objective_baselines": {"ecp": 4.721, "dwl": 589825.0},
        "design_bundle_sha256": "1a6ae4470ced5edbf2918264ecf72263b3c971fbc79bae14ad40f382c8de3b2b",
        "pdk_bundle_sha256": "b79ef8e150597efd12d479842f5e84014acd4a31e54deeaa0614b2875fa5ea81",
        "toolchain_receipt_sha256": "2ef873471db757b2003c3a52afbc0827fecbd80ec8c815eefc5d0ccbb8b160ec",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("refusing to overwrite A2 initializer evidence")
    if _sha256(LOCK) != LOCK_SHA:
        raise ValueError("A2-ORFO source lock drift")
    output.mkdir(parents=True, exist_ok=True)
    domain = A2ORFODomain.from_upstream(
        source_root=SOURCE, design="aes", platform_name="sky130hd",
        experiment_protocol=_protocol())
    manifest = a2_orfo_plugin_manifest(
        SOURCE, model_root=MODEL, python_executable=PYTHON,
        codex_executable=CODEX, default_timeout_seconds=600)
    runtime = WorkflowRuntime(
        RuntimeStore(output / "runtime.sqlite"), PluginRegistry([manifest]),
        workspace_root=output / "work", worker_id="a2-native-initializer")
    task = build_a2_orfo_initialization_task(
        project_id="a2-orfo-bootstrap-acceptance", design_id="aes",
        objective="ECP", domain=domain, count=4, optimizer_seed=37,
        task_id="a2-orfo-native-bootstrap", timeout_seconds=600)
    run = runtime.submit(task, capability="optimizer.l2.a2-orfo-initialize")
    terminal = runtime.execute_once(run.run_id)
    view = runtime.describe(run.run_id)
    if terminal.status is not RuntimeStatus.SUCCEEDED:
        raise RuntimeError(f"A2 initializer Runtime terminal status: {terminal.status.value}")
    matches = [(attempt, artifact) for stage in view["stages"]
               for attempt in stage["attempts"] for artifact in attempt["artifacts"]
               if artifact["kind"] == "optimizer_candidates"]
    if len(matches) != 1:
        raise ValueError("A2 initializer candidate artifact is ambiguous")
    attempt, artifact = matches[0]
    candidate_path = (Path(attempt["workspace"]) / artifact["store_key"]).resolve()
    if _sha256(candidate_path) != artifact["sha256"]:
        raise ValueError("A2 initializer candidate artifact hash mismatch")
    candidates = json.loads(candidate_path.read_text())
    trace_path = next((output / "work").rglob("a2_policy_trace.json"))
    trace = json.loads(trace_path.read_text())
    provider_path = next((output / "work").rglob("model_provider_trace.json"))
    provider = json.loads(provider_path.read_text())
    checks = {
        "runtime_succeeded": terminal.status is RuntimeStatus.SUCCEEDED,
        "native_upstream_entrypoint": trace["entrypoint"] ==
            "OptimizationWorkflow.generate_initial_parameters",
        "four_bootstrap_candidates": len(candidates) == 4,
        "all_12_dimensions": all(tuple(item) == A2_ORFO_PARAMETERS
                                   for item in candidates),
        "variable_clock_retained": all("CLK" in item for item in candidates),
        "no_model_call_for_random_initializer": provider["calls"] == [],
        "registered_candidate_hash_valid": _sha256(candidate_path) == artifact["sha256"],
        "source_lock_unchanged": _sha256(LOCK) == LOCK_SHA,
    }
    summary = {
        "schema_version": 1,
        "kind": "a2-orfo-native-initializer-acceptance",
        "accepted": all(checks.values()),
        "source_lock": {"source_document": str(LOCK.relative_to(ROOT)),
                        "sha256": LOCK_SHA},
        "run_id": run.run_id, "runtime_status": terminal.status.value,
        "task": task.to_dict(), "candidates": candidates,
        "candidate_artifact": artifact, "trace": trace,
        "checks": checks,
        "claim_boundary": (
            "A native A2-ORFO 12-D bootstrap generation Runtime smoke. It generates "
            "initial candidates but does not execute ORFS or claim measured QoR. The "
            "durable controller executes each point before policy fitting."),
    }
    path = output / "summary.json"
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    digest = _sha256(path)
    (output / "summary.sha256").write_text(f"{digest}  summary.json\n")
    print(json.dumps({"accepted": summary["accepted"], "summary": str(path),
                      "sha256": digest, "run_id": run.run_id}, indent=2))
    return 0 if summary["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
