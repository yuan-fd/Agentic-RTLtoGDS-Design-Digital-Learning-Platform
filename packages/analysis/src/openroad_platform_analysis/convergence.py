"""Deterministic, direction-aware convergence classification."""

from __future__ import annotations

from uuid import uuid4

from openroad_platform_contracts import (
    ConvergenceAssessment, ConvergencePolicy, ConvergenceState,
    MetricTrajectory, ObjectiveDirection,
)


def classify_convergence(trajectory: MetricTrajectory,
                         policy: ConvergencePolicy) -> ConvergenceAssessment:
    """Classify a comparable measured tail without hiding failed points.

    A terminal failure or too-short successful tail is ``unknown``.  Positive
    signed deltas always mean improvement, regardless of objective direction.
    """
    trajectory.validate()
    policy.validate()
    points = trajectory.points
    evidence = tuple(dict.fromkeys(
        (*trajectory.evidence, *(pointer for point in points for pointer in point.evidence))))

    if points[-1].terminal_status != "succeeded":
        return _assessment(trajectory, policy, ConvergenceState.UNKNOWN,
                           "latest_point_not_measured", points, (), (), evidence)

    successful_tail = []
    for point in reversed(points):
        if point.terminal_status != "succeeded":
            break
        successful_tail.append(point)
    successful_tail.reverse()
    if len(successful_tail) < policy.minimum_successful_points:
        return _assessment(trajectory, policy, ConvergenceState.UNKNOWN,
                           "insufficient_successful_tail", successful_tail or points[-1:],
                           (), (), evidence)

    sign = 1.0 if trajectory.direction is ObjectiveDirection.MAXIMIZE else -1.0
    deltas = tuple(sign * (float(right.value) - float(left.value))
                   for left, right in zip(successful_tail, successful_tail[1:]))
    tolerances = tuple(max(
        float(policy.absolute_tolerance),
        float(policy.relative_tolerance) * max(abs(float(left.value)), 1e-12),
    ) for left in successful_tail[:-1])

    divergence_transitions = policy.divergence_window - 1
    if (len(deltas) >= divergence_transitions
            and all(delta < -tolerance for delta, tolerance in
                    zip(deltas[-divergence_transitions:],
                        tolerances[-divergence_transitions:]))):
        return _assessment(trajectory, policy, ConvergenceState.DIVERGING,
                           "consecutive_material_regression", successful_tail,
                           deltas, tolerances, evidence)

    stall_transitions = policy.stall_window - 1
    if (len(deltas) >= stall_transitions
            and all(abs(delta) <= tolerance for delta, tolerance in
                    zip(deltas[-stall_transitions:], tolerances[-stall_transitions:]))):
        return _assessment(trajectory, policy, ConvergenceState.STALLED,
                           "no_material_change_in_window", successful_tail,
                           deltas, tolerances, evidence)

    if deltas[-1] > tolerances[-1]:
        return _assessment(trajectory, policy, ConvergenceState.IMPROVING,
                           "latest_material_improvement", successful_tail,
                           deltas, tolerances, evidence)

    return _assessment(trajectory, policy, ConvergenceState.UNKNOWN,
                       "mixed_or_inconclusive_trend", successful_tail,
                       deltas, tolerances, evidence)


def _assessment(trajectory, policy, state, reason, points, deltas,
                tolerances, evidence):
    result = ConvergenceAssessment(
        assessment_id=f"convergence-{uuid4().hex}",
        trajectory_id=trajectory.trajectory_id,
        policy_id=policy.policy_id,
        state=state,
        reason_code=reason,
        considered_point_ids=tuple(item.point_id for item in points),
        signed_benefit_deltas=tuple(deltas),
        transition_tolerances=tuple(tolerances),
        evidence=evidence,
    )
    result.validate()
    return result
