"""TaskSpec construction for the dataset-only ORFS-Agent bridge."""
from __future__ import annotations

import uuid
from typing import Any, Mapping, Sequence

from openroad_platform_contracts import TaskSpec

from .orfs_agent_domain import ORFSAgentDomain


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
                    inputs={"design": design_id, "platform": domain.platform, "objective": objective,
                            "observations": [dict(item) for item in observations], "parameter_domain": domain.to_dict()},
                    labels={"optimizer_origin": "external:ORFS-Agent", "execution_owner": "platform-runtime"})
    task.validate()
    return task
