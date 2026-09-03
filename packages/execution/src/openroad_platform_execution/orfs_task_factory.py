"""Thin ORFS implementation of the generic RTL-to-GDS task-factory port."""

from __future__ import annotations

import dataclasses
from typing import Any, Mapping

from openroad_platform_contracts.platform import TaskSpec
from openroad_platform_contracts.task_factory import RTL_TO_GDS_CAPABILITY, RTLToGDSRequest

from .orfs_plugin import ORFS_PLUGIN_ID, build_orfs_task


_BUILD_OPTION_KEYS = frozenset({
    "clock", "platform_name", "target_stage", "clock_period_ns",
    "core_utilization_pct", "place_density", "or_seed",
    "minimum_die_size_um", "stage_timeout_seconds", "timeout_seconds",
    "max_attempts",
})
_SCALAR_PARAMETER_KEYS = frozenset({
    "core_utilization_pct", "place_density", "minimum_die_size_um",
})


class ORFSRTLToGDSFactory:
    """Map the capability port to the existing ORFS builder without new logic."""

    capability = RTL_TO_GDS_CAPABILITY

    def build(self, request: RTLToGDSRequest) -> TaskSpec:
        request.validate()
        if request.capability != self.capability:
            raise ValueError(f"Unsupported capability: {request.capability}")
        options = dict(request.options)
        unknown = sorted(set(options) - _BUILD_OPTION_KEYS)
        if unknown:
            raise ValueError(f"Unsupported ORFS task options: {', '.join(unknown)}")
        task = build_orfs_task(
            request.rtl_path,
            project_id=request.project_id,
            design_id=request.design_id,
            top=request.top,
            task_id=request.task_id,
            labels=dict(request.labels),
            **options,
        )
        self.validate_task(task)
        return task

    def validate_task(self, task: TaskSpec) -> None:
        task.validate()
        if task.plugin_id != ORFS_PLUGIN_ID:
            raise ValueError("ORFS RTL-to-GDS factory requires an ORFS TaskSpec")

    def reconfigure(self, task: TaskSpec, values: Mapping[str, Any]) -> TaskSpec:
        """Apply the established ORFS allowlist without Scheduler knowing it."""
        self.validate_task(task)
        if not isinstance(values, Mapping) or not all(isinstance(key, str) for key in values):
            raise ValueError("parameter updates must be a string-keyed mapping")
        unknown = sorted(set(values) - _SCALAR_PARAMETER_KEYS)
        if unknown:
            raise ValueError("ORFS RTL-to-GDS factory does not admit: " + ", ".join(unknown))
        parameters = dict(task.parameters)
        parameters.update(values)
        result = dataclasses.replace(task, parameters=parameters)
        self.validate_task(result)
        return result
