#!/usr/bin/env python3
"""Bounded acceptance for the A2-ORFO product-route migration.

This freezes and persists the native 151-measurement shape but deliberately
does not submit an optimizer or EDA task.  Native policy/feedback and real
ORFS measurement are covered by the retained Slice 030 evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
for source_root in (ROOT, *(ROOT / "packages" / name / "src" for name in
                            ("contracts", "analysis", "scheduler", "execution"))):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from apps.l1_workbench.service import WorkbenchService  # noqa: E402
from openroad_platform_contracts import PluginManifest  # noqa: E402
from openroad_platform_contracts.product_surface import (  # noqa: E402
    DEFAULT_PRODUCT_SURFACE, ProductRole,
)
from openroad_platform_execution import (  # noqa: E402
    A2_ORFO_PARAMETERS, A2ORFODomain, ORFSAgentFullDomain,
)
from openroad_platform_scheduler import (  # noqa: E402
    A2_ORFO_CAMPAIGN_KIND, A2ORFOCampaignService, PipelineCheckpointStore,
)


A2_SOURCE = ROOT / "var/external-sources/a2-orfo-8b20a3c-clean"
ORFS_SOURCE = ROOT / "var/external-sources/orfs-agent-730f1fa-clean-20260901"
A2_COMMIT = "8b20a3c1f22934a39c7ba51ed0ec6dffe730da2d"
SINGLE_FEEDBACK = ROOT / "var/evidence/a2-orfo-single-feedback-20260905-r4/summary.json"
SINGLE_FEEDBACK_SHA = "c11638e49bf345987afda2f7159856a67cb4b1f962ceb6a8520d95f6ff7f55aa"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _Registry:
    def resolve(self, plugin_id, *, capability, **_kwargs):
        admitted = {
            ("a2-orfo", "optimizer.l2.a2-orfo-initialize"),
            ("a2-orfo", "optimizer.l2.a2-orfo-policy"),
            ("a2-orfo", "optimizer.l2.a2-orfo-feedback"),
            ("orfs-agent", "optimizer.l2.upstream-full-candidate"),
        }
        if (plugin_id, capability) not in admitted:
            raise LookupError((plugin_id, capability))
        return object()


class _NoExecutionRuntime:
    def __init__(self):
        self.registry = _Registry()
        self.tasks = []

    def submit_idempotent(self, task, *, capability):
        self.tasks.append((task, capability))
        raise AssertionError("configuration acceptance must not submit work")


def _protocols() -> tuple[dict, dict]:
    common = {
        "design": "aes", "platform": "sky130hd",
        "objective_set": ["ECP", "DWL", "COMBO"],
        "design_bundle_sha256": "1" * 64,
        "pdk_bundle_sha256": "2" * 64,
        "toolchain_receipt_sha256": "3" * 64,
    }
    a2 = {
        **common, "protocol_id": "a2-orfo-product-full-v1",
        "a2_orfo_commit": A2_COMMIT,
        "orfs_executor_commit": "730f1fa11f9c17c0aaac332412af2b2538f42e9b",
        "seed_policy": "a2-upstream-six-iteration-seed-policy-v1",
        "budget": {"minimum_successful_observations": 4, "feedback_steps": 5},
        "evaluator": "protected-orfs-agent-full-v1",
        "objective_baselines": {"ecp": 4.721, "dwl": 589825.0},
    }
    execution = {
        **common, "protocol_id": "a2-orfo-product-orfs-execution-v1",
        "orfs_agent_commit": "730f1fa11f9c17c0aaac332412af2b2538f42e9b",
        "orfs_commit": "ce8d36a7fef0ab9c47d183bcf078bce0f60f5a54",
        "seed_policy": "a2-upstream-six-iteration-seed-policy-v1",
        "budget": {"initial_samples": 26, "rounds": 5,
                   "suggestions_per_round": 25, "confirmations": 0},
        "evaluator": "protected-orfs-agent-full-v1",
        "initialization_method":
            "upstream:A2-ORFO.OptimizationWorkflow.generate_initial_parameters",
    }
    return a2, execution


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("refusing to overwrite A2 product migration evidence")
    output.mkdir(parents=True, exist_ok=True)

    workbench = WorkbenchService(output / "workbench", backend="smoke")
    budget = dict(workbench.l2_protocol_budget)
    expected_runs = (budget["initial_samples"]
                     + budget["feedback_steps"] * budget["suggestions_per_step"]
                     + budget["confirmations"])

    rule = DEFAULT_PRODUCT_SURFACE.rule_for(ProductRole.L2_OPTIMIZATION)
    old_manifest = PluginManifest(
        "orfs-agent", "historical", ("adapter",),
        ("optimizer.l2.upstream-full-12d",), (platform.machine(),),
        {"type": "object"}, {"type": "object"})
    old_rejected = False
    try:
        DEFAULT_PRODUCT_SURFACE.authorize(ProductRole.L2_OPTIMIZATION, old_manifest)
    except PermissionError:
        old_rejected = True

    a2_protocol, execution_protocol = _protocols()
    a2_domain = A2ORFODomain.from_upstream(
        source_root=A2_SOURCE, design="aes", platform_name="sky130hd",
        experiment_protocol=a2_protocol)
    execution_domain = ORFSAgentFullDomain.from_upstream(
        source_root=ORFS_SOURCE, design="aes", platform="sky130hd",
        experiment_protocol=execution_protocol)
    checkpoint_store = PipelineCheckpointStore(output / "campaign.sqlite")
    authorized = checkpoint_store.create_or_get(
        pipeline_kind=A2_ORFO_CAMPAIGN_KIND, subject_id="product-migration",
        owner_id=None, initial_state={
            "status": "authorized",
            "request": {"plugin_id": "a2-orfo",
                        "capability": "optimizer.l2.a2-orfo-feedback",
                        "budget": {"max_eda_runs": 151, "max_parallel": 4}},
            "authorization": {"authorization_id": "product-migration"},
            "goal": {"project_id": "tutorial", "design_id": "aes"},
        })
    runtime = _NoExecutionRuntime()
    configured = A2ORFOCampaignService(
        checkpoints=checkpoint_store, runtime=runtime, runtime_store=runtime,
        observation_for_run=lambda *_: {}, policy_result_for_run=lambda *_: {},
    ).configure(
        authorized["pipeline_id"], a2_domain=a2_domain,
        execution_domain=execution_domain, objective="ECP",
        initial_observations=(),
        optimizer_seeds=(401, 403, 405, 407, 409, 411), or_seed=401,
        n_suggestions=25, confirmation_seeds=(), bootstrap_samples=26)
    recovered = PipelineCheckpointStore(output / "campaign.sqlite").get(
        configured["pipeline_id"])
    state = recovered["state"]

    server_source = (ROOT / "apps/l1_workbench/server.py").read_text()
    worker_source = (ROOT / "apps/l1_workbench/a2_campaign_worker.py").read_text()
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=A2_SOURCE, text=True).strip()
    checks = {
        "product_role_is_a2_feedback": (rule.plugin_id, rule.capability) == (
            "a2-orfo", "optimizer.l2.a2-orfo-feedback"),
        "old_orfs_optimizer_rejected": old_rejected,
        "pinned_upstream_head": head == A2_COMMIT,
        "native_launcher_budget": budget == {
            "initial_samples": 26, "feedback_steps": 5,
            "suggestions_per_step": 25, "confirmations": 0},
        "full_151_measurement_budget": expected_runs == state["required_eda_runs"] == 151,
        "full_12d_shared_domain": len(A2_ORFO_PARAMETERS) == 12
            and set(A2_ORFO_PARAMETERS) == set(execution_domain.to_dict()["parameter_names"]),
        "variable_clock_retained": "CLK" in A2_ORFO_PARAMETERS,
        "configured_without_execution": runtime.tasks == [],
        "durable_checkpoint_reopened": recovered["revision"] == configured["revision"]
            and state["status"] == "bootstrap_pending",
        "http_forces_scheduling_only":
            'svc.l2_advance(sid,x["pipeline_id"],execute=False' in server_source,
        "os_worker_owns_execution":
            "service.l2_campaign.advance(" in worker_source and "execute=True" in worker_source,
        "prior_real_feedback_evidence_intact": _sha256(SINGLE_FEEDBACK) == SINGLE_FEEDBACK_SHA,
    }
    summary = {
        "schema_version": 1,
        "kind": "a2-orfo-product-migration-acceptance",
        "accepted": all(checks.values()),
        "pipeline_id": configured["pipeline_id"],
        "campaign_revision": configured["revision"],
        "product_rule": {"plugin_id": rule.plugin_id, "capability": rule.capability},
        "budget": budget,
        "required_eda_runs": state["required_eda_runs"],
        "parameter_names": list(A2_ORFO_PARAMETERS),
        "upstream": {
            "commit": head,
            "maindriver_sha256": _sha256(A2_SOURCE / "maindriver.sh"),
            "run_sequential_sha256": _sha256(A2_SOURCE / "run_sequential.sh"),
        },
        "checks": checks,
        "prior_real_feedback_evidence": {
            "path": str(SINGLE_FEEDBACK.relative_to(ROOT)),
            "sha256": SINGLE_FEEDBACK_SHA,
        },
        "claim_boundary": (
            "This acceptance proves product routing, complete native-sized campaign "
            "configuration, durable persistence and API/worker execution separation. "
            "It submits none of the 151 EDA measurements; native A2->real ORFS->protected "
            "evaluator->A2 feedback is evidenced separately by Slice 030."),
    }
    summary_path = output / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    digest = _sha256(summary_path)
    (output / "summary.sha256").write_text(f"{digest}  summary.json\n")
    print(json.dumps({"accepted": summary["accepted"], "summary": str(summary_path),
                      "sha256": digest}, indent=2))
    return 0 if summary["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
