#!/usr/bin/env python3
"""Evidence-gated aggregation for official AutoTuner campaign cells."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import median


METRICS = ("setup_wns_ns", "area_um2", "power_W")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_digest(snapshot: dict) -> str:
    records = snapshot.get("files")
    if not isinstance(records, list) or snapshot.get("file_count") != len(records):
        return ""
    return hashlib.sha256(json.dumps(
        records, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


def _value_fingerprint(value: dict) -> str:
    return hashlib.sha256(json.dumps(
        {key: item for key, item in value.items() if key != "fingerprint"},
        sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


def _canonical_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


def _fairness_domain_errors(*, fairness: dict, fairness_config: dict,
                            binding: dict, invocation: dict,
                            protocol: dict) -> list[str]:
    semantic_manifest = {
        key: value for key, value in fairness.items()
        if key not in {"manifest_fingerprint", "config_path"}
    }
    expected_names = sorted((protocol.get("search_domains") or {}).get(
        "common_parameter_names") or [])
    observed_names = sorted(fairness.get("selected_parameter_names") or [])
    mapping_names = sorted(
        row.get("platform_parameter")
        for row in fairness.get("parameter_mapping") or [])
    expected_domain_fingerprint = _canonical_digest({
        "domain_id": fairness.get("domain_id"),
        "parameter_mapping": fairness.get("parameter_mapping") or [],
        "config": fairness_config,
    })
    bundle = invocation.get("fairness_bundle") or {}
    valid = (
        fairness.get("schema_version") == 2
        and fairness.get("domain_id") ==
            (protocol.get("search_domains") or {}).get("common_domain_id")
        and bool(expected_names) and observed_names == expected_names
        and mapping_names == expected_names
        and fairness.get("config_sha256") == _canonical_digest(fairness_config)
        and fairness.get("parameter_domain_fingerprint") ==
            expected_domain_fingerprint
        and fairness.get("manifest_fingerprint") ==
            _canonical_digest(semantic_manifest)
        and binding.get("search_domain_id") == fairness.get("domain_id")
        and sorted(binding.get("search_parameter_names") or []) == expected_names
        and binding.get("parameter_domain_fingerprint") ==
            expected_domain_fingerprint
        and binding.get("fairness_manifest_fingerprint") ==
            fairness.get("manifest_fingerprint")
        and binding.get("fairness_config_sha256") == fairness.get("config_sha256")
        and bundle.get("parameter_domain_fingerprint") ==
            expected_domain_fingerprint
        and bundle.get("manifest_fingerprint") == fairness.get("manifest_fingerprint")
    )
    return [] if valid else [
        "official fairness domain does not match frozen common domain"]


def aggregate_cell(cell: Path, *, protocol: dict,
                   campaign_runner_sha256: str | None = None,
                   campaign_controller_source_sha256: str | None = None,
                   campaign_python_environment_sha256: str | None = None) -> dict:
    errors = []
    if (cell / "EXCLUDED_FROM_FORMAL_STUDY.json").is_file():
        errors.append("cell is explicitly excluded from the formal study")
    required = ("cell-binding.json", "invocation-manifest.json", "result.json",
                "controller-source-snapshot.json", "python-environment.json")
    for name in required:
        if not (cell / name).is_file():
            errors.append(f"{name} missing")
    if errors:
        return {"cell": cell.name, "eligible": False, "errors": errors}
    binding = json.loads((cell / "cell-binding.json").read_text(encoding="utf-8"))
    invocation = json.loads((cell / "invocation-manifest.json").read_text(encoding="utf-8"))
    result = json.loads((cell / "result.json").read_text(encoding="utf-8"))
    source = json.loads(
        (cell / "controller-source-snapshot.json").read_text(encoding="utf-8"))
    python_environment = json.loads(
        (cell / "python-environment.json").read_text(encoding="utf-8"))
    if int(protocol.get("schema_version") or 0) >= 24:
        fairness_path = cell / "fair-config/fairness-manifest.json"
        config_path = cell / "fair-config/autotuner.fair.json"
        if not fairness_path.is_file() or not config_path.is_file():
            errors.append("official fairness-domain evidence is missing")
        else:
            fairness = json.loads(fairness_path.read_text(encoding="utf-8"))
            fairness_config = json.loads(config_path.read_text(encoding="utf-8"))
            errors.extend(_fairness_domain_errors(
                fairness=fairness, fairness_config=fairness_config,
                binding=binding, invocation=invocation, protocol=protocol))
    if binding.get("frozen_study_protocol_digest") != protocol["protocol_digest"]:
        errors.append("frozen study protocol digest mismatch")
    if binding.get("study_mode") != "paper":
        errors.append("official cell was not executed in paper mode")
    if binding.get("common_evaluator_schema") != 3:
        errors.append("common evaluator schema is not 3")
    if invocation.get("toolchain_validation", {}).get("validated") is not True:
        errors.append("pinned toolchain validation missing")
    if (binding.get("toolchain_validation_fingerprint") !=
            invocation.get("toolchain_validation", {}).get("validation_fingerprint")):
        errors.append("toolchain validation fingerprint mismatch")
    if binding.get("autotuner_source_sha256") != invocation.get("autotuner_source_sha256"):
        errors.append("pinned AutoTuner source fingerprint mismatch")
    generated = invocation.get("generated_design") or {}
    expected_source = (protocol.get("reproducibility", {}).get(
        "source_snapshot", {}).get(
            f"{binding.get('platform')}/{binding.get('design')}")
    )
    command = list(invocation.get("command") or ())
    try:
        invoked_design = command[command.index("--design") + 1]
    except (ValueError, IndexError):
        invoked_design = None
    try:
        invoked_experiment = command[command.index("--experiment") + 1]
    except (ValueError, IndexError):
        invoked_experiment = None
    expected_experiment = (
        f"v2-paper-{protocol['protocol_digest'][:10]}-"
        f"{binding.get('platform')}-{binding.get('design')}-"
        f"{binding.get('algorithm')}-o{binding.get('optimizer_seed')}-"
        f"r{binding.get('or_seed')}-b{binding.get('samples')}"
    )
    if (generated.get("schema_version") not in {2, 3}
            or generated.get("kind") != "pinned-orfs-reference-design-adapter"
            or generated.get("logical_design") != binding.get("design")
            or generated.get("namespace") != binding.get("execution_design")
            or invoked_design != binding.get("execution_design")
            or binding.get("experiment_namespace") != expected_experiment
            or invocation.get("experiment_namespace") != expected_experiment
            or invoked_experiment != expected_experiment
            or generated.get("identity_sha256") !=
                binding.get("generated_design_identity_sha256")
            or generated.get("sdc_sha256") !=
                binding.get("generated_design_sdc_sha256")
            or generated.get("comparison_identity_sha256") != expected_source):
        errors.append("official execution design is not the frozen content-addressed reference")
    if (campaign_runner_sha256 is not None
            and binding.get("runner_sha256") != campaign_runner_sha256):
        errors.append("official runner differs from the frozen campaign snapshot")
    source_digest = source.get("digest")
    if (_snapshot_digest(source) != source_digest
            or binding.get("controller_source_snapshot_sha256") != source_digest
            or invocation.get("controller_source_snapshot_sha256") != source_digest):
        errors.append("official evaluator source snapshot mismatch")
    if (campaign_controller_source_sha256 is not None
            and source_digest != campaign_controller_source_sha256):
        errors.append("official evaluator source differs across campaign cells")
    environment_fingerprint = python_environment.get("fingerprint")
    if (_value_fingerprint(python_environment) != environment_fingerprint
            or binding.get("python_environment_fingerprint") !=
                environment_fingerprint
            or invocation.get("python_environment_fingerprint") !=
                environment_fingerprint
            or (campaign_python_environment_sha256 is not None
                and environment_fingerprint != campaign_python_environment_sha256)):
        errors.append("official Python optimization environments differ from campaign")
    if binding.get("paired_or_seeds") != protocol["paired_or_seeds"]:
        errors.append("paired OR_SEED vector mismatch")
    if int(binding.get("samples") or 0) != max(protocol["budget_checkpoints"]):
        errors.append("official cell budget differs from frozen maximum")
    logical_budget = int(binding.get("samples") or 0)
    expected_upstream = logical_budget + 1
    if (binding.get("upstream_samples") != expected_upstream
            or binding.get("uncharged_warm_start_count") != 1
            or invocation.get("upstream_sample_count") != expected_upstream
            or invocation.get("logical_candidate_budget") != logical_budget):
        errors.append("official upstream and logical budget accounting mismatch")
    if (int(result.get("trial_count") or 0) != expected_upstream
            or int(result.get("logical_trial_count") or 0) != logical_budget
            or int(result.get("warm_start_trial_count") or 0) != 1):
        errors.append("official result did not execute baseline plus complete logical budget")
    if result.get("status") != "succeeded" or result.get("warm_start_errors"):
        errors.append("official warm-start or controller result is invalid")
    returncode = result.get("returncode")
    if returncode not in {0, 16}:
        errors.append("official controller ended with an infrastructure error")
    if (returncode == 16
            and int(result.get("successful_logical_trial_count") or 0) != 0):
        errors.append("AutoTuner no-success return code conflicts with result ledger")

    raw_trials = list(result.get("trials") or [])
    warm_trials = [trial for trial in raw_trials
                   if trial.get("budget_role") == "warm_start_baseline"]
    initial_points = generated.get("autotuner_initial_points") or []
    if (len(warm_trials) != 1 or len(initial_points) != 1
            or warm_trials[0].get("parameters") != initial_points[0]
            or warm_trials[0].get("logical_round") is not None
            or (warm_trials[0].get("common_evaluation") or {}).get("status") !=
                "not_required_uncharged_warm_start"
            or warm_trials[0].get("common_evaluations") not in (None, [])):
        errors.append("official uncharged baseline warm-start evidence mismatch")
    logical_raw = [trial for trial in raw_trials
                   if trial.get("budget_role") == "logical_candidate"]
    trials = []
    for logical_index, trial in enumerate(logical_raw, start=1):
        if trial.get("logical_round") != logical_index:
            errors.append("official logical candidate rounds are not contiguous")
        evaluations = trial.get("common_evaluations") or []
        verified = []
        trial_errors = []
        for expected_seed, record in zip(protocol["paired_or_seeds"], evaluations):
            if record.get("status") != "completed" or record.get("or_seed") != expected_seed:
                trial_errors.append(f"seed {expected_seed}: common evaluation incomplete")
                continue
            path = Path(str(record.get("path") or "")).expanduser().resolve()
            try:
                path.relative_to(cell.resolve())
            except ValueError:
                trial_errors.append(f"seed {expected_seed}: evaluation path escapes cell")
                continue
            if not path.is_file():
                trial_errors.append(f"seed {expected_seed}: evaluation artifact missing")
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            if (payload.get("schema_version") != 3
                    or payload.get("kind") != "common-orfs-signoff-evaluation"
                    or payload.get("identity", {}).get("or_seed") != expected_seed
                    or payload.get("normalized_stage_evidence", {}).get(
                        "units", {}).get("time", {}).get("status") != "verified"):
                trial_errors.append(f"seed {expected_seed}: evaluator evidence invalid")
                continue
            runtime_seconds = (payload.get("metrics") or {}).get("runtime_seconds")
            if (isinstance(runtime_seconds, bool)
                    or not isinstance(runtime_seconds, (int, float))
                    or not math.isfinite(float(runtime_seconds))
                    or float(runtime_seconds) <= 0):
                trial_errors.append(
                    f"seed {expected_seed}: positive wall-time evidence missing")
                continue
            verified.append({
                "or_seed": expected_seed, "evaluation_id": payload["evaluation_id"],
                "artifact_sha256": _sha256(path), "feasible": payload["feasible"],
                "metrics": payload["metrics"],
            })
        if evaluations and len(evaluations) != len(protocol["paired_or_seeds"]):
            trial_errors.append("paired replica count mismatch")
        if trial.get("accepted_by_upstream_metric") is True and not evaluations:
            trial_errors.append("upstream-accepted trial lacks common evaluation")
        if trial_errors and (evaluations or
                             trial.get("accepted_by_upstream_metric") is True):
            errors.append(
                f"trial {trial.get('trial_id')}: incomplete common evaluation")
        eligible = (not trial_errors and len(verified) == len(protocol["paired_or_seeds"])
                    and all(item["feasible"] is True for item in verified)
                    and all(metric in item["metrics"] and math.isfinite(
                        float(item["metrics"][metric])) for item in verified
                            for metric in METRICS))
        summary = ({metric: float(median([
            item["metrics"][metric] for item in verified])) for metric in METRICS}
                   if eligible else None)
        trials.append({
            "logical_round": logical_index, "trial_id": trial.get("trial_id"),
            "upstream_accepted": trial.get("accepted_by_upstream_metric") is True,
            "eligible": eligible, "summary_metrics": summary,
            "errors": trial_errors, "evaluations": verified,
        })
    if len(trials) != logical_budget:
        errors.append("official trial ledger length differs from fixed budget")
    return {
        "cell": cell.name, "eligible": not errors, "errors": errors,
        "binding": binding, "result_status": result.get("status"),
        "logical_budget": logical_budget,
        "observed_trial_count": len(trials),
        "upstream_trial_count": len(raw_trials),
        "uncharged_warm_start_count": len(warm_trials),
        "missing_budget_rounds": max(0, int(binding.get("samples") or 0) - len(trials)),
        "feasible_trial_count": sum(item["eligible"] for item in trials),
        "trials": trials,
        "claim_boundary": (
            "Missing, failed and infeasible trials remain in the logical budget and "
            "contribute zero until a feasible observed incumbent exists."),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=Path(__file__).resolve().parents[1] /
                        "studies/protocols/v2-industrial-dse-20260829-r27.protocol.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.campaign.expanduser().resolve()
    protocol = json.loads(args.protocol.expanduser().resolve().read_text(encoding="utf-8"))
    campaign = json.loads((root / "campaign-manifest.json").read_text(encoding="utf-8"))
    if campaign.get("protocol_digest") != protocol["protocol_digest"]:
        raise ValueError("official campaign protocol digest mismatch")
    cells = [aggregate_cell(
        root / "cells" / item["cell_id"], protocol=protocol,
        campaign_runner_sha256=campaign.get("runner_sha256"),
        campaign_controller_source_sha256=campaign.get(
            "controller_source_snapshot_sha256"),
        campaign_python_environment_sha256=campaign.get(
            "python_environment_fingerprint"))
             for item in campaign["cells"]]
    result = {
        "schema_version": 2, "kind": "official-autotuner-evidence-aggregation",
        "study_id": protocol.get("study_id"),
        "protocol_digest": protocol["protocol_digest"],
        "campaign_fingerprint": campaign["campaign_fingerprint"], "cells": cells,
        "eligible_cell_count": sum(item["eligible"] for item in cells),
        "ineligible_cell_count": sum(not item["eligible"] for item in cells),
        "all_cells_eligible": all(item["eligible"] for item in cells),
    }
    output = (args.output.expanduser().resolve() if args.output else
              root / "evidence-aggregation.json")
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8"); temporary.replace(output)
    print(json.dumps({"output": str(output),
                      "all_cells_eligible": result["all_cells_eligible"]}))
    return 0 if result["all_cells_eligible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
