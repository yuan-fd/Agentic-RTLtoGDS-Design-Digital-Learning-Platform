from __future__ import annotations

import pytest

from openroad_platform_analysis import classify_convergence
from openroad_platform_contracts import (
    ConvergencePolicy, ConvergenceState, EvidencePointer, MetricTrajectory,
    MetricTrajectoryPoint, ObjectiveDirection,
)


EVIDENCE = (EvidencePointer("artifact:metric", "a" * 64),)
PROTOCOL = "b" * 64


def _point(index, value, *, status="succeeded", protocol=PROTOCOL):
    return MetricTrajectoryPoint(
        f"point-{index}", index, f"run-{index}", f"attempt-{index}",
        "finish", "setup_wns_ns", "ns", status, protocol,
        "protected_evaluator", EVIDENCE,
        value=value if status == "succeeded" else None,
        failure_category=None if status == "succeeded" else "tool_failure",
    )


def _trajectory(values, *, direction=ObjectiveDirection.MAXIMIZE):
    return MetricTrajectory(
        "trajectory-1", "setup_wns_ns", "ns", direction, PROTOCOL,
        tuple(_point(index, value) for index, value in enumerate(values)), EVIDENCE)


POLICY = ConvergencePolicy("policy-1", 0.01, 0.0, 3, 3, 2)


@pytest.mark.parametrize(("values", "expected"), [
    ((-0.5, -0.3), ConvergenceState.IMPROVING),
    ((-0.3, -0.301, -0.299), ConvergenceState.STALLED),
    ((0.3, 0.1, -0.2), ConvergenceState.DIVERGING),
    ((-0.5, -0.2, -0.4), ConvergenceState.UNKNOWN),
])
def test_direction_aware_convergence(values, expected):
    assert classify_convergence(_trajectory(values), POLICY).state is expected


def test_minimize_direction_inverts_benefit():
    trajectory = MetricTrajectory(
        "trajectory-1", "power_W", "W", ObjectiveDirection.MINIMIZE, PROTOCOL,
        tuple(MetricTrajectoryPoint(
            f"point-{i}", i, f"run-{i}", f"attempt-{i}", "finish",
            "power_W", "W", "succeeded", PROTOCOL, "protected_evaluator",
            EVIDENCE, value=value) for i, value in enumerate((2.0, 1.5))), EVIDENCE)
    assert classify_convergence(trajectory, POLICY).state is ConvergenceState.IMPROVING


def test_failure_is_retained_and_forces_unknown():
    trajectory = MetricTrajectory(
        "trajectory-1", "setup_wns_ns", "ns", ObjectiveDirection.MAXIMIZE,
        PROTOCOL, (_point(0, -0.5), _point(1, None, status="failed")), EVIDENCE)
    result = classify_convergence(trajectory, POLICY)
    assert result.state is ConvergenceState.UNKNOWN
    assert result.reason_code == "latest_point_not_measured"
    assert result.considered_point_ids == ("point-0", "point-1")


def test_mixed_protocol_is_rejected_instead_of_compared():
    trajectory = MetricTrajectory(
        "trajectory-1", "setup_wns_ns", "ns", ObjectiveDirection.MAXIMIZE,
        PROTOCOL, (_point(0, -0.5), _point(1, -0.2, protocol="c" * 64)), EVIDENCE)
    with pytest.raises(ValueError, match="not comparable"):
        classify_convergence(trajectory, POLICY)


def test_contract_round_trip_preserves_typed_state():
    trajectory = _trajectory((-0.5, -0.4))
    assessment = classify_convergence(trajectory, POLICY)
    assert MetricTrajectory.from_dict(trajectory.to_dict()) == trajectory
    assert type(assessment).from_dict(assessment.to_dict()) == assessment
