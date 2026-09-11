"""Artifact-backed evidence reader shared by the L2 API and worker.

This module reads only Runtime-registered artifacts, verifies their content
hashes and workspace containment, and exports the rows accepted by the full
ORFS-Agent campaign controller.  It does not evaluate QoR itself.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


class ORFSAgentCampaignEvidence:
    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime

    def candidates_for_run(self, run_id: str):
        _artifact, payload = self.registered_json(run_id, "optimizer_candidates")
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise ValueError("registered ORFS-Agent candidate artifact must be an object list")
        return payload

    def a2_policy_result_for_run(self, run_id: str):
        candidate_artifact, candidates = self.registered_json(
            run_id, "optimizer_candidates")
        _checkpoint_artifact, checkpoint = self.registered_json(
            run_id, "optimizer_checkpoint")
        if not isinstance(candidates, list) or not all(
                isinstance(item, dict) for item in candidates):
            raise ValueError("registered A2 candidate artifact must be an object list")
        if not isinstance(checkpoint, dict):
            raise ValueError("registered A2 checkpoint artifact must be an object")
        return {
            "candidates": candidates, "checkpoint": checkpoint,
            "evidence_ref": f"runtime-artifact:{candidate_artifact['artifact_id']}",
        }

    def observation_for_run(self, run_id: str, _state: Mapping[str, Any]):
        run = self.runtime.store.get_run(run_id)
        task = run.task_spec
        candidate = task.inputs.get("candidate")
        domain = task.inputs.get("parameter_domain")
        if not isinstance(candidate, dict) or not isinstance(domain, dict):
            raise ValueError("candidate Runtime task lacks the full typed inputs")
        artifacts = self._artifacts(run_id)
        refs = [f"runtime-artifact:{item['artifact_id']}" for _attempt, item in artifacts
                if isinstance(item.get("artifact_id"), str)]
        base = {
            "run_id": run_id, "observation_id": f"orfs-agent-{run_id}",
            "status": run.status.value, "feasible": False,
            "protocol_sha256": domain.get("protocol_sha256"),
            "candidate": candidate, "metrics": {}, "artifact_refs": refs,
        }
        if run.status.value != "succeeded":
            return {**base, "failure_category": "candidate_runtime_terminal_failure"}
        official = [item for _attempt, item in artifacts
                    if item.get("metadata", {}).get("official_qor") is True
                    and item.get("metadata", {}).get("runtime_authority") == "protected_evaluator"
                    and item.get("metadata", {}).get("qor_semantics") ==
                    "candidate-variable-clock-signoff"]
        if len(official) != 1:
            return {**base, "status": "evidence_error",
                    "failure_category": "protected_evaluator_artifact_missing_or_ambiguous"}
        _artifact, evaluation = self.registered_json(
            run_id, "report", artifact_id=official[0]["artifact_id"])
        metadata = evaluation.get("run_metadata") or {}
        metrics = metadata.get("upstream_variable_clock_metrics")
        if not isinstance(metrics, dict):
            return {**base, "status": "evidence_error",
                    "failure_category": "upstream_objective_metrics_missing"}
        return {
            **base, "feasible": bool(evaluation.get("feasible")),
            "metrics": metrics,
            "protected_signoff_metrics": dict(evaluation.get("metrics") or {}),
            "protected_evaluation_id": evaluation.get("evaluation_id"),
        }

    def registered_json(self, run_id: str, kind: str, *, artifact_id: str | None = None):
        matches = [(attempt, item) for attempt, item in self._artifacts(run_id)
                   if item.get("kind") == kind
                   and (artifact_id is None or item.get("artifact_id") == artifact_id)]
        if len(matches) != 1:
            raise ValueError(f"Runtime run has ambiguous registered {kind} evidence")
        attempt, artifact = matches[0]
        root = Path(attempt["workspace"]).resolve()
        path = (root / artifact["store_key"]).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("registered artifact escapes Runtime workspace") from exc
        if hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
            raise ValueError("registered Runtime artifact hash changed")
        return artifact, json.loads(path.read_text(encoding="utf-8"))

    def _artifacts(self, run_id: str):
        view = self.runtime.describe(run_id)
        return [(attempt, item) for stage in view.get("stages", ())
                for attempt in stage.get("attempts", ())
                for item in attempt.get("artifacts", ())]
