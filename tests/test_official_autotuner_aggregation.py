import importlib.util
import hashlib
import json
from pathlib import Path


def _module():
    path = (Path(__file__).resolve().parents[1] /
            "scripts/aggregate_official_autotuner_campaign.py")
    spec = importlib.util.spec_from_file_location("official_aggregation", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_explicitly_excluded_official_cell_is_never_eligible(tmp_path):
    (tmp_path / "EXCLUDED_FROM_FORMAL_STUDY.json").write_text(json.dumps({
        "excluded": True, "reason": "mutable source",
    }))
    row = _module().aggregate_cell(tmp_path, protocol={})
    assert row["eligible"] is False
    assert any("explicitly excluded" in item for item in row["errors"])


def _write_minimal_cell(path: Path, *, samples: int, trials: list[dict],
                        returncode: int = 0, successful: int = 0):
    baseline = {"CORE_UTILIZATION": 40}
    experiment = f"v2-paper-p-asap7-ibex-hyperopt-o1103-r101-b{samples}"
    logical_trials = [{
        **trial, "budget_role": "logical_candidate", "logical_round": index,
    } for index, trial in enumerate(trials, start=1)]
    raw_trials = [{
        "trial_id": "warm", "parameters": baseline,
        "budget_role": "warm_start_baseline", "logical_round": None,
        "accepted_by_upstream_metric": True, "common_evaluations": [],
        "common_evaluation": {"status": "not_required_uncharged_warm_start"},
    }, *logical_trials]
    records = [{"path": "runner.py", "sha256": "a" * 64}]
    digest = hashlib.sha256(json.dumps(
        records, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    environment = {"schema_version": 1, "kind": "test-environment"}
    environment["fingerprint"] = hashlib.sha256(json.dumps(
        environment, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    (path / "controller-source-snapshot.json").write_text(json.dumps({
        "digest": digest, "file_count": 1, "files": records,
    }))
    (path / "python-environment.json").write_text(json.dumps(environment))
    (path / "cell-binding.json").write_text(json.dumps({
        "frozen_study_protocol_digest": "p", "study_mode": "paper",
        "common_evaluator_schema": 3, "paired_or_seeds": [101, 211, 307],
        "samples": samples, "toolchain_validation_fingerprint": "tool",
        "upstream_samples": samples + 1, "uncharged_warm_start_count": 1,
        "platform": "asap7", "design": "ibex",
        "algorithm": "hyperopt", "optimizer_seed": 1103, "or_seed": 101,
        "execution_design": "opv2_ibex_test",
        "experiment_namespace": experiment,
        "generated_design_identity_sha256": "identity",
        "generated_design_sdc_sha256": "sdc",
        "autotuner_source_sha256": "source", "runner_sha256": "runner",
        "controller_source_snapshot_sha256": digest,
        "python_environment_fingerprint": environment["fingerprint"],
    }))
    (path / "invocation-manifest.json").write_text(json.dumps({
        "toolchain_validation": {
            "validated": True, "validation_fingerprint": "tool"},
        "autotuner_source_sha256": "source",
        "controller_source_snapshot_sha256": digest,
        "python_environment_fingerprint": environment["fingerprint"],
        "upstream_sample_count": samples + 1,
        "logical_candidate_budget": samples,
        "experiment_namespace": experiment,
        "command": ["python", "-m", "autotuner.distributed", "--design",
                    "opv2_ibex_test", "--experiment", experiment],
        "generated_design": {
            "schema_version": 2,
            "kind": "pinned-orfs-reference-design-adapter",
            "logical_design": "ibex", "namespace": "opv2_ibex_test",
            "identity_sha256": "identity", "sdc_sha256": "sdc",
            "comparison_identity_sha256": None,
            "autotuner_initial_points": [baseline],
        },
    }))
    (path / "result.json").write_text(json.dumps({
        "returncode": returncode, "status": "succeeded",
        "trial_count": len(raw_trials), "logical_trial_count": len(logical_trials),
        "warm_start_trial_count": 1, "warm_start_errors": [],
        "successful_trial_count": successful + 1,
        "successful_logical_trial_count": successful, "trials": raw_trials,
    }))
    return digest


def _protocol(samples: int):
    return {"protocol_digest": "p", "paired_or_seeds": [101, 211, 307],
            "budget_checkpoints": [samples]}


def test_official_aggregation_rejects_incomplete_fixed_budget(tmp_path):
    _write_minimal_cell(tmp_path, samples=2, trials=[{
        "trial_id": "rejected", "accepted_by_upstream_metric": False,
        "common_evaluations": [],
    }])
    row = _module().aggregate_cell(tmp_path, protocol=_protocol(2))
    assert row["eligible"] is False
    assert any("complete logical budget" in item for item in row["errors"])


def test_official_aggregation_rejects_accepted_trial_without_replay(tmp_path):
    _write_minimal_cell(tmp_path, samples=1, successful=1, trials=[{
        "trial_id": "accepted", "accepted_by_upstream_metric": True,
        "common_evaluations": [],
    }])
    row = _module().aggregate_cell(tmp_path, protocol=_protocol(1))
    assert row["eligible"] is False
    assert any("incomplete common evaluation" in item for item in row["errors"])


def test_fairness_domain_binding_recomputes_config_and_manifest_fingerprints():
    module = _module()
    names = ["core_utilization_pct", "place_density_lb_addon",
             "global_placement_padding", "cts_cluster_size",
             "cts_cluster_diameter"]
    mapping = [{"platform_parameter": name, "range": [0, index + 1]}
               for index, name in enumerate(names)]
    config = {name.upper(): {"type": "int", "minmax": [0, index + 2], "step": 1}
              for index, name in enumerate(names)}
    fairness = {
        "schema_version": 2,
        "kind": "official-openroad-autotuner-fairness-adapter",
        "domain_id": "official_autotuner_independent_v2",
        "selected_parameter_names": sorted(names),
        "parameter_mapping": mapping,
        "config_sha256": module._canonical_digest(config),
    }
    fairness["parameter_domain_fingerprint"] = module._canonical_digest({
        "domain_id": fairness["domain_id"], "parameter_mapping": mapping,
        "config": config})
    fairness["manifest_fingerprint"] = module._canonical_digest(fairness)
    binding = {
        "search_domain_id": fairness["domain_id"],
        "search_parameter_names": sorted(names),
        "parameter_domain_fingerprint": fairness["parameter_domain_fingerprint"],
        "fairness_manifest_fingerprint": fairness["manifest_fingerprint"],
        "fairness_config_sha256": fairness["config_sha256"],
    }
    invocation = {"fairness_bundle": {
        "parameter_domain_fingerprint": fairness["parameter_domain_fingerprint"],
        "manifest_fingerprint": fairness["manifest_fingerprint"],
    }}
    protocol = {"search_domains": {
        "common_domain_id": fairness["domain_id"],
        "common_parameter_names": names,
    }}
    assert module._fairness_domain_errors(
        fairness=fairness, fairness_config=config, binding=binding,
        invocation=invocation, protocol=protocol) == []
    config["CORE_UTILIZATION_PCT"]["minmax"][-1] += 1
    assert "does not match frozen common domain" in module._fairness_domain_errors(
        fairness=fairness, fairness_config=config, binding=binding,
        invocation=invocation, protocol=protocol)[0]
