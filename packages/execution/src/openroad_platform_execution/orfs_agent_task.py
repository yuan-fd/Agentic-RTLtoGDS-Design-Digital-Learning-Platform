"""TaskSpec construction for the dataset-only ORFS-Agent bridge."""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import replace
from typing import Any, Mapping, Sequence

from openroad_platform_contracts import TaskSpec

from .orfs_agent_domain import (
    FULL_OBJECTIVES, FULL_PARAMETER_NAMES, ORFSAgentDomain, ORFSAgentFullDomain,
)


def build_orfs_agent_dataset_task(*, project_id: str, design_id: str, objective: str,
                                  observations: Sequence[Mapping[str, Any]], domain: ORFSAgentDomain,
                                  task_id: str | None = None, timeout_seconds: int = 1800) -> TaskSpec:
    if not observations or not all(isinstance(item, Mapping) for item in observations):
        raise ValueError("ORFS-Agent needs non-empty Runtime observation objects")
    for observation in observations:
        domain.validate_observation(observation)
    task = TaskSpec(task_id=task_id or f"orfs-agent-{uuid.uuid4().hex}", project_id=project_id,
                    design_id=design_id, plugin_id="orfs-agent", timeout_seconds=timeout_seconds,
                    max_attempts=1, expected_artifacts=("optimizer_dataset", "optimizer_input_manifest", "upstream_source_lock"),
                    inputs={"mode": "materialize_dataset", "design": design_id,
                            "platform": domain.platform, "objective": objective,
                            "observations": [dict(item) for item in observations], "parameter_domain": domain.to_dict()},
                    labels={"optimizer_origin": "external:ORFS-Agent", "execution_owner": "platform-runtime"})
    task.validate()
    return task


def build_orfs_agent_native_task(*, project_id: str, design_id: str, objective: str,
                                 observations: Sequence[Mapping[str, Any]], domain: ORFSAgentDomain,
                                 n_suggestions: int, optimizer_seed: int,
                                 task_id: str | None = None, timeout_seconds: int = 1800) -> TaskSpec:
    """Request bounded upstream GP/EI; domain and observations stay typed."""
    if not isinstance(n_suggestions, int) or not 1 <= n_suggestions <= 64:
        raise ValueError("n_suggestions must be between 1 and 64")
    if not isinstance(optimizer_seed, int) or optimizer_seed < 0:
        raise ValueError("optimizer_seed must be non-negative")
    base = build_orfs_agent_dataset_task(project_id=project_id, design_id=design_id,
        objective=objective, observations=observations, domain=domain, task_id=task_id,
        timeout_seconds=timeout_seconds)
    task = replace(base, inputs={**base.inputs, "mode": "native_agent",
                                  "n_suggestions": n_suggestions, "optimizer_seed": optimizer_seed},
                   expected_artifacts=(*base.expected_artifacts, "optimizer_candidates", "optimizer_trace"))
    task.validate(); return task


def build_orfs_agent_full_policy_task(
    *, project_id: str, design_id: str, objective: str,
    observations: Sequence[Mapping[str, Any]], domain: ORFSAgentFullDomain,
    n_suggestions: int, optimizer_seed: int, task_id: str | None = None,
    timeout_seconds: int = 1800,
) -> TaskSpec:
    """Invoke upstream GP/EI without reducing its published 12-D domain."""
    if objective not in FULL_OBJECTIVES:
        raise ValueError("full ORFS-Agent objective must be ECP, DWL, or COMBO")
    if not isinstance(n_suggestions, int) or not 1 <= n_suggestions <= 64:
        raise ValueError("n_suggestions must be between 1 and 64")
    if not isinstance(optimizer_seed, int) or optimizer_seed < 0:
        raise ValueError("optimizer_seed must be non-negative")
    if len(observations) < 2 or not all(isinstance(item, Mapping) for item in observations):
        raise ValueError("full ORFS-Agent policy requires at least two measured observations")
    for observation in observations:
        domain.validate_observation(observation)
    task = TaskSpec(
        task_id=task_id or f"orfs-agent-full-{uuid.uuid4().hex}",
        project_id=project_id,
        design_id=design_id,
        plugin_id="orfs-agent",
        inputs={
            "mode": "upstream_full_policy",
            "design": domain.design,
            "platform": domain.platform,
            "objective": objective,
            "observations": [dict(item) for item in observations],
            "parameter_domain": domain.to_dict(),
            "n_suggestions": n_suggestions,
            "optimizer_seed": optimizer_seed,
        },
        timeout_seconds=timeout_seconds,
        max_attempts=1,
        expected_artifacts=("optimizer_dataset", "optimizer_candidates", "optimizer_trace", "upstream_source_lock"),
        labels={
            "optimizer_origin": "external:ORFS-Agent@upstream-full-12d",
            "execution_owner": "platform-runtime",
            "variable_clock_semantics": "true",
        },
    )
    task.validate()
    return task


def build_orfs_agent_full_initialization_task(
    *, project_id: str, design_id: str, objective: str,
    domain: ORFSAgentFullDomain, count: int, initialization_seed: int,
    task_id: str | None = None, timeout_seconds: int = 1800,
) -> TaskSpec:
    """Invoke the pinned upstream initializer over the complete typed domain."""
    if objective not in FULL_OBJECTIVES:
        raise ValueError("full ORFS-Agent objective must be ECP, DWL, or COMBO")
    if not isinstance(count, int) or not 2 <= count <= 512:
        raise ValueError("full ORFS-Agent initialization count must be between 2 and 512")
    if not isinstance(initialization_seed, int) or initialization_seed < 0:
        raise ValueError("initialization_seed must be non-negative")
    task = TaskSpec(
        task_id=task_id or f"orfs-agent-initialize-{uuid.uuid4().hex}",
        project_id=project_id, design_id=design_id, plugin_id="orfs-agent",
        inputs={"mode": "upstream_full_initialize", "design": domain.design,
                "platform": domain.platform, "objective": objective,
                "parameter_domain": domain.to_dict(), "count": count,
                "initialization_seed": initialization_seed},
        timeout_seconds=timeout_seconds, max_attempts=1,
        expected_artifacts=("optimizer_candidates", "optimizer_trace", "upstream_source_lock"),
        labels={"optimizer_origin": "external:ORFS-Agent@upstream-full-12d",
                "initialization_owner": "upstream", "execution_owner": "platform-runtime",
                "variable_clock_semantics": "true"},
    )
    task.validate()
    return task


def build_orfs_agent_full_candidate_task(
    *, project_id: str, design_id: str, objective: str,
    domain: ORFSAgentFullDomain, candidate: Mapping[str, Any],
    or_seed: int,
    proposal_origin: str = "external:ORFS-Agent@upstream-full-12d",
    proposal_evidence_refs: Sequence[str] = (),
    task_id: str | None = None, timeout_seconds: int = 10_800,
) -> TaskSpec:
    """Execute one complete upstream candidate through the same plugin ID."""
    if objective not in FULL_OBJECTIVES:
        raise ValueError("full ORFS-Agent objective must be ECP, DWL, or COMBO")
    if isinstance(or_seed, bool) or not isinstance(or_seed, int) or or_seed < 0:
        raise ValueError("full ORFS-Agent candidate OR_SEED must be non-negative")
    if not isinstance(proposal_origin, str) or not proposal_origin:
        raise ValueError("candidate proposal origin must be a non-empty string")
    if not all(isinstance(ref, str) and ref for ref in proposal_evidence_refs):
        raise ValueError("candidate proposal evidence references must be non-empty strings")
    domain.validate_candidate(candidate)
    ordered_candidate = {name: candidate[name] for name in FULL_PARAMETER_NAMES}
    candidate_sha256 = hashlib.sha256(json.dumps(
        ordered_candidate, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    task = TaskSpec(
        task_id=task_id or f"orfs-agent-candidate-{uuid.uuid4().hex}",
        project_id=project_id, design_id=design_id, plugin_id="orfs-agent",
        inputs={"mode": "upstream_full_candidate", "design": domain.design,
                "platform": domain.platform, "objective": objective,
                "parameter_domain": domain.to_dict(), "candidate": ordered_candidate,
                "proposal_origin": proposal_origin,
                "proposal_evidence_refs": list(proposal_evidence_refs)},
        parameters={"protocol": "orfs-agent-upstream-full-candidate-v1",
                    "candidate_sha256": candidate_sha256, "or_seed": or_seed},
        resources={"toolchain_profile": "orfs-agent-paper-pinned"},
        timeout_seconds=timeout_seconds, max_attempts=1,
        expected_artifacts=("optimizer_input_manifest", "optimizer_dataset",
                            "upstream_source_lock", "log", "report",
                            "odb", "def", "netlist", "sdc", "spef"),
        labels={"optimizer_origin": proposal_origin,
                "reproduction_mode": "variable-clock-upstream-semantics",
                "execution_owner": "platform-runtime"},
    )
    task.validate()
    return task
