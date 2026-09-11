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
        if (manifest.plugin_id == "orfs-agent"
                and task.inputs.get("mode") == "upstream_full_candidate"):
            return self._evaluate_full_candidate(task=task, workspace=workspace)
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

    def _evaluate_full_candidate(
        self, *, task: TaskSpec, workspace: str,
    ) -> tuple[dict[str, Any], ...]:
        """Score one upstream-variable-clock candidate from raw ORFS signoff evidence."""
        root = Path(workspace).expanduser().resolve()
        output = root / "protected_orfs_agent_evaluation.json"
        try:
            materialization = _json(root / "candidate_materialization.json")
            domain = task.inputs.get("parameter_domain")
            candidate = task.inputs.get("candidate")
            if not isinstance(domain, dict) or not isinstance(candidate, dict):
                raise ValueError("full candidate task lacks its typed domain or candidate")
            protocol = domain.get("experiment_protocol")
            if not isinstance(protocol, dict):
                raise ValueError("full candidate task lacks its immutable experiment protocol")
            if (materialization.get("kind") != "orfs-agent-paper-candidate-materialization"
                    or materialization.get("candidate") != candidate
                    or materialization.get("design") != task.inputs.get("design")
                    or materialization.get("platform") != task.inputs.get("platform")):
                raise ValueError("candidate materialization does not match the typed TaskSpec")
            or_seed = task.parameters.get("or_seed")
            if materialization.get("or_seed") != or_seed:
                raise ValueError("candidate materialization does not match Runtime OR_SEED")
            platform = str(task.inputs["platform"])
            clock = float(candidate["CLK"])
            clock_period_ns = clock / 1000.0 if platform == "asap7" else clock
            upstream_metrics_path = _inside(root, root / "candidate_metrics.json")
            upstream_metrics = _json(upstream_metrics_path)
            proposal_origin = str(task.inputs.get("proposal_origin") or
                                  "external:ORFS-Agent@upstream-full-12d")
            source_kind = ("a2-orfo-proposed-runtime-orfs-candidate"
                           if proposal_origin.startswith("external:A2-ORFO@")
                           else "orfs-agent-upstream-variable-clock-candidate")
            evaluation = evaluate_orfs_run(
                log_dir=_inside(root, Path(str(materialization["expected_report_directory"]))),
                result_dir=_inside(root, Path(str(materialization["expected_result_directory"]))),
                platform=platform,
                design=str(task.inputs["design"]),
                design_identity_sha256=str(protocol["design_bundle_sha256"]),
                effective_config_sha256=_sha256(
                    _inside(root, Path(str(materialization["private_config"])))
                ),
                or_seed=int(or_seed),
                source_kind=source_kind,
                clock_period_ns=clock_period_ns,
                run_metadata={
                    "task_id": task.task_id,
                    "protocol_sha256": domain.get("protocol_sha256"),
                    "objective": task.inputs.get("objective"),
                    "proposal_origin": proposal_origin,
                    "proposal_evidence_refs": list(task.inputs.get("proposal_evidence_refs") or ()),
                    "candidate": candidate,
                    "candidate_clock": {"raw": clock,
                                        "raw_unit": "ps" if platform == "asap7" else "ns",
                                        "canonical_ns": clock_period_ns},
                    "upstream_variable_clock_metrics": upstream_metrics,
                    "upstream_metrics_are_canonical_signoff": False,
                    "pdk_bundle_sha256": protocol.get("pdk_bundle_sha256"),
                    "toolchain_receipt_sha256": protocol.get("toolchain_receipt_sha256"),
                },
            )
            write_immutable_evaluation(output, evaluation)
            return (_artifact(
                root, output, outcome="completed", evaluation=evaluation,
                extra_metadata={
                    "qor_semantics": "candidate-variable-clock-signoff",
                    "fixed_sdc_fair_comparison": False,
                    "upstream_metric_artifact": upstream_metrics_path.name,
                },
            ),)
        except Exception as exc:
            error = root / "protected_orfs_agent_evaluator_error.log"
            error.write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
            return (_artifact(
                root, error, outcome="error", error=f"{type(exc).__name__}: {exc}",
                extra_metadata={
                    "qor_semantics": "candidate-variable-clock-signoff",
                    "fixed_sdc_fair_comparison": False,
                },
            ),)


def _artifact(root: Path, path: Path, *, outcome: str, evaluation: dict | None = None,
              error: str | None = None,
              extra_metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    canonical_metrics = ({name: value for name, value in evaluation["metrics"].items()
                          if isinstance(value, (int, float)) and not isinstance(value, bool)}
                         if evaluation is not None else {})
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
            **({"canonical_metrics": canonical_metrics} if evaluation is not None else {}),
            **({"error": error} if error else {}),
            **dict(extra_metadata or {}),
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
