from __future__ import annotations

from dataclasses import replace

from openroad_platform_analysis import MemoryPolicy, PersistentOptimizationMemory
from openroad_platform_contracts import (
    EvidencePointer, LearningContext, LearningObservation, ObjectiveSpec,
)


def _context(design="gcd"):
    return LearningContext(
        design_id=design, design_fingerprint="a" * 64, platform="asap7",
        pdk_id="asap7", toolchain_id="orfs-pinned", flow_stage="finish",
        metric_parser_version="metrics21",
    )


def _observation(index, *, context=None, succeeded=True, parameters=None):
    context = context or _context()
    util = 30 + index
    run_id = f"run-{context.design_id}-{index}"
    return LearningObservation(
        observation_id=f"observation-{context.design_id}-{index}", context=context,
        parameters=parameters or {"util": util, "dpo": index % 2},
        metrics={"area": 200 - 2 * util, "wns": -.5 + .01 * util} if succeeded else {},
        metric_units={"area": "um2", "wns": "ns"} if succeeded else {},
        status="succeeded" if succeeded else "failed", cost_seconds=10 + index,
        run_id=run_id, attempt_id=f"attempt-{context.design_id}-{index}",
        evidence=(EvidencePointer(ref=f"run:{run_id}", sha256=f"{index % 10}" * 64),),
        failure_category=None if succeeded else "flow_failure",
    )


OBJECTIVES = (ObjectiveSpec("area", "min"), ObjectiveSpec("wns", "max"))


def test_memory_artifacts_are_inert_until_corroborated(tmp_path):
    memory = PersistentOptimizationMemory(
        tmp_path / "memory.db",
        MemoryPolicy(minimum_corroborating_configurations=12,
                     minimum_absolute_spearman=.3),
    )
    for index in range(11):
        snapshot = memory.ingest(_observation(index), OBJECTIVES)
    sensitivities = [item for item in snapshot["artifacts"]
                     if item["kind"] == "parameter_sensitivity"]
    assert sensitivities and all(item["status"] == "candidate" for item in sensitivities)
    assert not any(item["kind"] == "parameter_sensitivity"
                   for item in snapshot["active_artifacts"])
    snapshot = memory.ingest(_observation(11), OBJECTIVES)
    assert any(item["kind"] == "parameter_sensitivity"
               for item in snapshot["active_artifacts"])
    assert snapshot["unique_configuration_count"] == 12


def test_repeated_failure_rule_has_exact_scope_and_evidence_gate(tmp_path):
    memory = PersistentOptimizationMemory(
        tmp_path / "memory.db", MemoryPolicy(minimum_corroborating_configurations=3))
    params = {"util": 80, "dpo": 1}
    for index in range(3):
        snapshot = memory.ingest(_observation(index, succeeded=False, parameters=params), OBJECTIVES)
    failure = next(item for item in snapshot["active_artifacts"]
                   if item["kind"] == "failure_region")
    assert failure["support_count"] == 3
    assert failure["payload"]["scope"] == "exact effective configuration only"
    assert len(failure["payload"]["evidence_refs"]) == 3
    snapshot = memory.ingest(
        _observation(3, succeeded=True, parameters=params), OBJECTIVES)
    retired = next(item for item in snapshot["artifacts"]
                   if item["kind"] == "failure_region")
    assert retired["status"] == "retired"
    assert retired["contradiction_count"] == 1


def test_memory_is_exact_context_partitioned_and_idempotent(tmp_path):
    memory = PersistentOptimizationMemory(tmp_path / "memory.db")
    first = _observation(0)
    memory.ingest(first, OBJECTIVES)
    memory.ingest(first, OBJECTIVES)
    other = _context("ibex")
    memory.ingest(_observation(0, context=other), OBJECTIVES)
    assert memory.snapshot(first.context.fingerprint)["observation_count"] == 1
    assert memory.snapshot(other.fingerprint)["observation_count"] == 1


def _grid_observation(index, x, y, *, context):
    base = _observation(index, context=context, parameters={"x": x, "y": y})
    return replace(base, metrics={"area": float(x * y), "wns": float(-x * y)},
                   metric_units={"area": "um2", "wns": "ns"})


def test_interaction_requires_discovery_and_holdout_agreement(tmp_path):
    memory = PersistentOptimizationMemory(tmp_path / "memory.db")
    context = _context()
    index = 0
    for x in range(-2, 3):
        for y in range(-2, 3):
            snapshot = memory.ingest(
                _grid_observation(index, x, y, context=context), OBJECTIVES)
            index += 1
    interactions = [item for item in snapshot["active_artifacts"]
                    if item["kind"] == "parameter_interaction"]
    assert interactions
    area = next(item for item in interactions if item["payload"]["metric"] == "area")
    assert area["payload"]["parameters"] == ["x", "y"]
    assert area["payload"]["discovery_standardized_effect"] > 0
    assert area["payload"]["holdout_standardized_effect"] > 0
    assert len(area["payload"]["holdout_configuration_ids"]) >= 4


def test_cross_design_transfer_is_inert_until_target_holdout_matches(tmp_path):
    memory = PersistentOptimizationMemory(tmp_path / "memory.db")
    source, target = _context("gcd"), _context("ibex")
    index = 0
    for context in (source, target):
        for x in range(-2, 3):
            for y in range(-2, 3):
                memory.ingest(_grid_observation(index, x, y, context=context), OBJECTIVES)
                index += 1
    transfers = memory.propose_transfers(source.fingerprint, target.fingerprint)
    assert transfers and all(item["status"] == "candidate" for item in transfers)
    interaction = next(item for item in transfers
                       if item["kind"] == "parameter_interaction"
                       and item["payload"]["source_artifact"]["payload"]["metric"] == "area")
    validated = memory.validate_transfer(interaction["transfer_id"], OBJECTIVES)
    assert validated["status"] == "active"
    assert validated["payload"]["target_holdout_artifact"]["status"] == "active"
    assert validated["payload"]["execution_allowed"] is False


def test_evidence_verifier_blocks_poisoned_observation(tmp_path):
    memory = PersistentOptimizationMemory(
        tmp_path / "memory.db", evidence_verifier=lambda _observation: False)
    import pytest
    with pytest.raises(ValueError, match="failed Runtime verification"):
        memory.ingest(_observation(0), OBJECTIVES)
