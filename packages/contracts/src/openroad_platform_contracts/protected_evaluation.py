"""Dependency-free post-execution evaluation boundary.

An adapter owns an upstream tool's native execution.  A protected evaluator is
invoked by Runtime only after that adapter has returned and its raw artifacts
have passed path/hash validation.  It may derive immutable evidence, but it
cannot schedule a task, mutate a benchmark, or write Runtime state directly.
"""

from __future__ import annotations

from typing import Any, Protocol

from .platform import PluginManifest, TaskSpec


class ProtectedEvaluator(Protocol):
    """Produce validated workspace-relative evidence after one successful task."""

    def evaluate(
        self,
        *,
        manifest: PluginManifest,
        task: TaskSpec,
        workspace: str,
    ) -> tuple[dict[str, Any], ...]:
        """Return additional artifact declarations, never Runtime state."""
