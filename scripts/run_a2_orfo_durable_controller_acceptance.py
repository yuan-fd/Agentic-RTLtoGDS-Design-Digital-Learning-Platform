#!/usr/bin/env python3
"""Replay the real A2 single loop through the durable campaign controller."""

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

from apps.l1_workbench.l2_campaign_evidence import ORFSAgentCampaignEvidence  # noqa: E402
from openroad_platform_execution import A2ORFODomain, ORFSAgentFullDomain  # noqa: E402
from openroad_platform_scheduler import (  # noqa: E402
    A2_ORFO_CAMPAIGN_KIND, A2ORFOCampaignService, PipelineCheckpointStore,
    RuntimeStore,
)


SOURCE = ROOT / "var/evidence/a2-orfo-single-feedback-20260905-r4"
SUMMARY = SOURCE / "summary.json"
SUMMARY_SHA = "c11638e49bf345987afda2f7159856a67cb4b1f962ceb6a8520d95f6ff7f55aa"
RUNTIME_DB = SOURCE / "runtime.sqlite"
RUNTIME_SHA = "ec1973da9cd9a67b572596c80969e92532c18a9b2b27036314ecad88a486dd91"
A2_SOURCE = ROOT / "var/external-sources/a2-orfo-8b20a3c-clean"
ORFS_SOURCE = ROOT / "var/external-sources/orfs-agent-730f1fa-clean-20260901"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _Registry:
    def resolve(self, plugin_id, *, capability, **_kwargs):
        if (plugin_id, capability) not in {
            ("a2-orfo", "optimizer.l2.a2-orfo-initialize"),
            ("a2-orfo", "optimizer.l2.a2-orfo-policy"),
            ("a2-orfo", "optimizer.l2.a2-orfo-feedback"),
            ("orfs-agent", "optimizer.l2.upstream-full-candidate"),
        }:
            raise LookupError((plugin_id, capability))
        return object()


class _PinnedReplayRuntime:
    """Read-only mapping from deterministic controller tasks to real run IDs."""

    def __init__(self, store, source):
        self.store = store; self.registry = _Registry(); self.source = source
        self.submissions = []
        self.run_map = {
            "policy": source["runs"]["first_policy"]["run_id"],
            "candidate": source["runs"]["candidate_execution"]["run_id"],
            "feedback": source["runs"]["feedback_policy"]["run_id"],
        }

    def submit_idempotent(self, task, *, capability):
        if task.plugin_id == "orfs-agent":
            role = "candidate"
            if task.inputs["candidate"] != self.source["first_candidate"]:
                raise ValueError("controller candidate differs from real A2 proposal")
        else:
            role = "policy" if capability.endswith("-policy") else "feedback"
        run = self.store.get_run(self.run_map[role])
        if (run.task_spec.plugin_id != task.plugin_id
                or run.task_spec.inputs["mode"] != task.inputs["mode"]):
            raise ValueError("replay mapping does not preserve plugin/mode")
        self.submissions.append({"task_id": task.task_id, "capability": capability,
                                 "mapped_run_id": run.run_id, "role": role})
        return run

    def execute_once(self, run_id):
        # Deliberately read-only: these runs are already Runtime-terminal.
        return self.store.get_run(run_id)

    def describe(self, run_id):
        role = next(value for value, mapped in self.run_map.items() if mapped == run_id)
        key = {"policy": "first_policy", "candidate": "candidate_execution",
               "feedback": "feedback_policy"}[role]
        run = self.source["runs"][key]
        return {"run": {"run_id": run_id, "status": run["status"]},
                "stages": [{"stage_key": "plugin", "attempts": run["attempts"]}]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("refusing to overwrite durable A2 controller evidence")
    if (_sha256(SUMMARY), _sha256(RUNTIME_DB)) != (SUMMARY_SHA, RUNTIME_SHA):
        raise ValueError("real A2 loop evidence drift")
    output.mkdir(parents=True, exist_ok=True)
    source = json.loads(SUMMARY.read_text())
    store = RuntimeStore(RUNTIME_DB)
    replay = _PinnedReplayRuntime(store, source)
    evidence = ORFSAgentCampaignEvidence(replay)

    def policy_result(run_id):
        candidate_artifact, candidates = evidence.registered_json(
            run_id, "optimizer_candidates")
        _checkpoint_artifact, checkpoint = evidence.registered_json(
            run_id, "optimizer_checkpoint")
        return {"candidates": candidates, "checkpoint": checkpoint,
                "evidence_ref": f"runtime-artifact:{candidate_artifact['artifact_id']}"}

    a2_domain = A2ORFODomain.from_upstream(
        source_root=A2_SOURCE, design="aes", platform_name="sky130hd",
        experiment_protocol=source["protocols"]["a2_policy"])
    execution_domain = ORFSAgentFullDomain.from_upstream(
        source_root=ORFS_SOURCE, design="aes", platform="sky130hd",
        experiment_protocol=source["protocols"]["runtime_execution"])
    first = store.get_run(source["runs"]["first_policy"]["run_id"])
    initial_observations = first.task_spec.inputs["observations"]

    checkpoints = PipelineCheckpointStore(output / "a2_controller.sqlite")
    checkpoint = checkpoints.create_or_get(
        pipeline_kind=A2_ORFO_CAMPAIGN_KIND,
        subject_id="l2-auth-real-a2-replay", owner_id=None,
        initial_state={
            "status": "authorized",
            "request": {"plugin_id": "a2-orfo",
                        "capability": "optimizer.l2.a2-orfo-feedback",
                        "budget": {"max_eda_runs": 1, "max_parallel": 1}},
            "authorization": {"authorization_id": "l2-auth-real-a2-replay"},
            "goal": {"project_id": "a2-orfo-acceptance", "design_id": "aes"},
        })
    service = A2ORFOCampaignService(
        checkpoints=checkpoints, runtime=replay, runtime_store=store,
        observation_for_run=evidence.observation_for_run,
        policy_result_for_run=policy_result)
    checkpoint = service.configure(
        checkpoint["pipeline_id"], a2_domain=a2_domain,
        execution_domain=execution_domain, objective="ECP",
        initial_observations=initial_observations,
        optimizer_seeds=(41, 43), or_seed=701, n_suggestions=1)

    statuses = [checkpoint["state"]["status"]]
    for index in range(20):
        # Reconstruct the service on every transition to prove restart safety.
        service = A2ORFOCampaignService(
            checkpoints=PipelineCheckpointStore(output / "a2_controller.sqlite"),
            runtime=replay, runtime_store=store,
            observation_for_run=evidence.observation_for_run,
            policy_result_for_run=policy_result)
        checkpoint = service.advance(checkpoint["pipeline_id"], execute=True,
                                     max_parallel=1)
        statuses.append(checkpoint["state"]["status"])
        if checkpoint["state"]["status"] in {
                "completed", "failed", "diagnosis_required"}:
            break
    state = checkpoint["state"]
    checks = {
        "controller_completed": state["status"] == "completed",
        "one_real_feedback_step": len(state["iterations"]) == 1 and
            len(state["measured_observations"]) == 1,
        "full_12d_preserved": len(state["a2_domain"]["parameter_names"]) == 12 and
            set(state["a2_domain"]["parameter_names"]) == set(source["first_candidate"]),
        "real_policy_candidate_preserved":
            state["iterations"][0]["candidates"][0]["candidate"] ==
            source["first_candidate"],
        "protected_feedback_preserved":
            state["measured_observations"][0].get("protected_evaluation_id") ==
            source["feedback"].get("protected_evaluation_id"),
        "real_next_candidate_preserved": state["final_next_candidates"][0] ==
            source["next_candidate"],
        "policy_then_feedback_capability": [item["capability"] for item in
                                             replay.submissions if item["role"] != "candidate"] == [
            "optimizer.l2.a2-orfo-policy", "optimizer.l2.a2-orfo-feedback"],
        "candidate_delegated_to_orfs_agent": any(
            item["role"] == "candidate" and
            item["capability"] == "optimizer.l2.upstream-full-candidate"
            for item in replay.submissions),
        "durable_restart_progress": len(statuses) >= 5 and checkpoint["revision"] >= 5,
        "source_runtime_unchanged": _sha256(RUNTIME_DB) == RUNTIME_SHA,
        "source_summary_unchanged": _sha256(SUMMARY) == SUMMARY_SHA,
    }
    result = {
        "schema_version": 1,
        "kind": "a2-orfo-durable-controller-acceptance",
        "accepted": all(checks.values()),
        "source": {"summary": str(SUMMARY.relative_to(ROOT)),
                   "summary_sha256": SUMMARY_SHA,
                   "runtime_database_sha256": RUNTIME_SHA},
        "pipeline_id": checkpoint["pipeline_id"],
        "revision": checkpoint["revision"],
        "status_history": statuses,
        "submission_mapping": replay.submissions,
        "final_state": state,
        "checks": checks,
        "claim_boundary": (
            "A durable controller replay over the already executed real A2 policy -> "
            "ORFS -> protected evaluator -> A2 feedback loop. It validates restart and "
            "evidence consumption without rerunning EDA. The source single-loop smoke "
            "remains the execution proof; neither artifact is a full campaign or PPA claim."
        ),
    }
    path = output / "summary.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    digest = _sha256(path)
    (output / "summary.sha256").write_text(f"{digest}  summary.json\n")
    print(json.dumps({"accepted": result["accepted"], "summary": str(path),
                      "sha256": digest, "pipeline_id": checkpoint["pipeline_id"]},
                     indent=2))
    return 0 if result["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
