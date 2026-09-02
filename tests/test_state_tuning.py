from __future__ import annotations

from openroad_platform_analysis.state_tuning import (
    compact_policy_evidence, EvidenceBoundSearchPolicy, SearchMode, StatefulL2Controller,
)
from openroad_platform_contracts import (
    AgentBudget, DesignState, EvidencePointer, LearningContext,
    LearningObservation, ObjectiveSpec, OptimizationStudy, OptimizerProposal,
    ParameterSpec,
)


def _evidence(ref="run:run-1"):
    return EvidencePointer(ref=ref, sha256="a" * 64)


def _study():
    return OptimizationStudy(
        study_id="study-1", design_id="aes", context_fingerprint="b" * 64,
        parameter_space=(
            ParameterSpec("util", 40, 70, kind="int", step=5, stage="floorplan"),
            ParameterSpec("padding", 0, 4, kind="int", step=1, stage="place"),
            ParameterSpec("cts_size", 10, 40, kind="int", step=5, stage="cts"),
        ),
        objectives=(ObjectiveSpec("setup_wns_ns", "max", .5),
                    ObjectiveSpec("area_um2", "min", .5)),
        hard_constraints=(
            {"metric": "setup_wns_ns", "operator": ">=", "threshold": 0.0},
            {"metric": "drc_errors", "operator": "<=", "threshold": 0.0},
        ), max_runs=100, seed=7,
    )


def _state():
    return DesignState("state-1", "goal-1", 1, "observed", "finish",
                       {"setup_wns_ns": -0.1}, AgentBudget(80, 20, 3600, 4),
                       evidence=(_evidence("artifact:report"),),
                       diagnosis={"dominant_stage": "cts"})


def _observation(index: int, *, wns: float, util: int = 50, padding: int = 1,
                 cts: int = 20):
    context = LearningContext(
        design_id="aes", design_fingerprint="c" * 64, platform="asap7",
        pdk_id="asap7", toolchain_id="orfs-pinned", flow_stage="finish",
        metric_parser_version="v1",
    )
    return LearningObservation(
        observation_id=f"obs-{index}", context=context,
        parameters={"util": util, "padding": padding, "cts_size": cts},
        metrics={"setup_wns_ns": wns, "area_um2": 100.0 + index,
                 "drc_errors": 0.0},
        metric_units={"setup_wns_ns": "ns", "area_um2": "um2", "drc_errors": "count"},
        status="succeeded", cost_seconds=5, run_id=f"run-{index}",
        attempt_id=f"attempt-{index}", evidence=(_evidence(f"run:run-{index}"),),
    )


def test_state_policy_enters_feasibility_recovery_without_safe_anchor():
    decision = EvidenceBoundSearchPolicy().decide(
        _study(), _state(), (_observation(1, wns=-0.2),))
    assert decision.mode is SearchMode.FEASIBILITY_RECOVERY
    assert set(decision.parameter_subset) == {"util", "padding", "cts_size"}


def test_state_policy_uses_only_active_holdout_validated_interaction():
    decision = EvidenceBoundSearchPolicy().decide(
        _study(), _state(), (_observation(1, wns=0.1),), memory_snapshot={
            "active_artifacts": [{"kind": "parameter_interaction", "payload": {
                "parameters": ["util", "padding"]}}],
        })
    assert decision.mode is SearchMode.INTERACTION_SCREENING
    assert decision.parameter_subset == ("util", "padding")


def test_compact_policy_evidence_keeps_queryable_handles_and_is_bounded():
    pointers = (
        _evidence("artifact:z"), _evidence("run:run-2"),
        _evidence("source:study:one"), _evidence("edair:run-2"),
        _evidence("artifact:a"), _evidence("run:run-1"),
        _evidence("artifact:z"),
    )
    selected = compact_policy_evidence(pointers, maximum=4)
    assert [item.ref for item in selected] == [
        "edair:run-2", "run:run-1", "run:run-2", "source:study:one",
    ]


def test_controller_projects_full_observations_to_policy_subspace():
    study = _study(); state = _state()
    decision = EvidenceBoundSearchPolicy().decide(
        study, state, (_observation(1, wns=0.1),), memory_snapshot={
            "active_artifacts": [{"kind": "parameter_interaction", "payload": {
                "parameters": ["util", "padding"]}}],
        })
    seen = {}

    class FakeBackend:
        def propose_batch(self, scoped, observations, **kwargs):
            rows = tuple(observations); seen["names"] = [item.name for item in scoped.parameter_space]
            seen["row_parameters"] = rows[0].parameters
            return (OptimizerProposal(
                proposal_id="proposal-1", study_id=scoped.study_id, candidate_id="candidate-1",
                iteration=0, parameters={"util": 55, "padding": 2}, predictions=(),
                acquisition_value=0.2, evidence=(_evidence("artifact:model"),),
            ),)

    controller = StatefulL2Controller()
    controller._backend = lambda mode: FakeBackend()  # type: ignore[method-assign]
    proposals = controller.propose(study, state, (_observation(1, wns=0.1),),
                                   batch_size=1,
                                   baseline_metrics={"setup_wns_ns": 0.0, "area_um2": 101.0},
                                   decision=decision)
    assert seen["names"] == ["util", "padding"]
    assert seen["row_parameters"] == {"util": 50, "padding": 1}
    assert proposals[0].model_metadata["state_tuning"]["mode"] == "interaction_screening"
