"""Protected ORFS signoff evaluation invoked by Runtime after adapter success."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from openroad_platform_contracts.platform import PluginManifest, TaskSpec

from .common_evaluator import SCHEMA_VERSION, evaluate_orfs_run, write_immutable_evaluation


class ORFSProtectedEvaluator:
    """Derive canonical ORFS QoR from raw, Runtime-validated workspace evidence.

    This class intentionally owns no database connection, process launch,
    optimizer policy, benchmark mutation or Runtime status transition.  Its
    only output is an immutable workspace-relative evidence artifact which
    Runtime validates and registers.
    """

    def evaluate(
        self,
        *,
        manifest: PluginManifest,
        task: TaskSpec,
        workspace: str,
    ) -> tuple[dict[str, Any], ...]:
        if manifest.plugin_id != "orfs" or task.parameters.get("target_stage") != "finish":
            return ()
        root = Path(workspace).expanduser().resolve()
        implementation = root / "orfs" / "implementation"
        output = implementation / "analysis" / "common_evaluation.json"
        try:
            _inside(root, implementation)
            plan = _json(implementation / "plan.json")
            run_result = _json(implementation / "run_result.json")
            request = plan["request"]
            design = str(plan["design"])
            platform = str(request["platform"])
            identity = str(task.labels.get("design_bundle_sha256") or "")
            if not re.fullmatch(r"[0-9a-f]{64}", identity):
                identity = _sha256(implementation / "design_input_manifest.json")
            stages = run_result.get("stages") or []
            evaluation = evaluate_orfs_run(
                log_dir=implementation / "logs" / platform / design / "base",
                result_dir=implementation / "results" / platform / design / "base",
                platform=platform,
                design=design,
                design_identity_sha256=identity,
                effective_config_sha256=_sha256(
                    _inside(implementation, Path(str(plan["config_path"])))
                ),
                or_seed=int(request["or_seed"]),
                source_kind="native-platform-orfs",
                clock_period_ns=float(request["clock_period_ns"]),
                runtime_seconds=sum(float(item.get("seconds") or 0.0) for item in stages),
                run_metadata={
                    "run_id": str(plan["run_id"]),
                    "target_stage": str(request["target_stage"]),
                    "stage_statuses": [
                        {key: item.get(key) for key in ("stage", "status", "returncode", "seconds")}
                        for item in stages if isinstance(item, dict)
                    ],
                },
            )
            write_immutable_evaluation(output, evaluation)
            return (_artifact(root, output, outcome="completed", evaluation=evaluation),)
        except Exception as exc:
            # ``implementation`` is adapter-produced and can be a symlink.
            # Once _inside() has rejected it, never use it again for a write:
            # error evidence must remain under Runtime's attempt workspace.
            error = root / "protected_evaluator_error.log"
            error.parent.mkdir(parents=True, exist_ok=True)
            error.write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
            return (_artifact(root, error, outcome="error", error=f"{type(exc).__name__}: {exc}"),)


def _artifact(root: Path, path: Path, *, outcome: str, evaluation: dict | None = None,
              error: str | None = None) -> dict[str, Any]:
    return {
        "kind": "report",
        "path": str(path.resolve().relative_to(root)),
        "metadata": {
            "producer": "protected-orfs-evaluator",
            "official_qor": outcome == "completed",
            "outcome": outcome,
            "evaluator_schema_version": SCHEMA_VERSION,
            **({"evaluation_id": evaluation["evaluation_id"], "feasible": evaluation["feasible"]}
               if evaluation is not None else {}),
            **({"error": error} if error else {}),
        },
    }


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inside(root: Path, candidate: Path) -> Path:
    """Resolve an adapter-produced path and reject references outside its workspace."""
    resolved_root = root.resolve()
    resolved_candidate = candidate.expanduser().resolve()
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(
            f"Protected evaluator input escapes its workspace: {candidate}"
        ) from exc
    return resolved_candidate
