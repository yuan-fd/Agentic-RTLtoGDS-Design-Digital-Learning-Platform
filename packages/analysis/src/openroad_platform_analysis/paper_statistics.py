"""Failure-inclusive, paired statistics for preregistered DSE experiments."""

from __future__ import annotations

import hashlib
import itertools
import math
import random
from statistics import median
from typing import Iterable, Mapping, Sequence


def anytime_hypervolume_summary(
    optimization_trace: Mapping[str, object] | None, *,
    budget: int, checkpoints: Sequence[int] = (),
) -> dict:
    """Integrate observed feasible HV over every logical proposal, including zeros."""
    if not 1 <= int(budget) <= 1_000_000:
        raise ValueError("budget must be a positive logical configuration count")
    if any(not 1 <= int(item) <= budget for item in checkpoints):
        raise ValueError("checkpoints must lie inside the fixed budget")
    rows = list((optimization_trace or {}).get("trace") or [])
    by_round: dict[int, float] = {}
    for item in rows:
        round_index = int(item["configuration_round"])
        value = float(item["hypervolume"])
        if not 1 <= round_index <= budget or not math.isfinite(value) or value < 0:
            raise ValueError("hypervolume trace contains an invalid round or value")
        by_round[round_index] = max(value, by_round.get(round_index, 0.0))
    current = 0.0
    sequence = []
    for round_index in range(1, budget + 1):
        current = max(current, by_round.get(round_index, 0.0))
        sequence.append(current)
    return {
        "budget": budget,
        "auc": float(sum(sequence)),
        "normalized_auc": float(sum(sequence) / budget),
        "final_hypervolume": sequence[-1],
        "checkpoint_hypervolume": {
            str(item): sequence[int(item) - 1] for item in checkpoints
        },
        "checkpoint_normalized_auc": {
            str(item): float(sum(sequence[:int(item)]) / int(item))
            for item in checkpoints
        },
        "first_positive_round": next(
            (index + 1 for index, value in enumerate(sequence) if value > 0), None),
        "missing_or_infeasible_rounds_count_as_zero_or_carry_forward": True,
        "unit": "observed replicated full-flow feasible hypervolume by logical proposal",
    }


def baseline_improvement_summary(
    history: Sequence[Mapping[str, object]], *, budget: int,
    checkpoints: Sequence[int] = (),
) -> dict:
    """Locate the first feasible observation that beats baseline utility.

    Feasible hypervolume is positive even for a point equal to baseline because
    its reference point is negative. Therefore HV>0 is not an improvement test.
    """
    if not 1 <= int(budget) <= 1_000_000:
        raise ValueError("budget must be a positive logical configuration count")
    if any(not 1 <= int(item) <= budget for item in checkpoints):
        raise ValueError("checkpoints must lie inside the fixed budget")
    improving = []
    for item in history:
        if item.get("kind") != "bo_candidate":
            continue
        round_index = int(item.get("round") or 0)
        if not 1 <= round_index <= budget:
            raise ValueError("candidate round lies outside the fixed budget")
        summary, utility = item.get("summary"), item.get("utility")
        if (isinstance(summary, Mapping) and summary.get("eligible") is True
                and isinstance(utility, (int, float))
                and math.isfinite(float(utility)) and float(utility) > 0):
            improving.append(round_index)
    first = min(improving, default=None)
    return {
        "budget": int(budget),
        "first_feasible_baseline_improving_round": first,
        "checkpoint_attained": {
            str(item): first is not None and first <= int(item)
            for item in checkpoints
        },
        "attained_by_final_budget": first is not None,
        "target": (
            "common-evaluator eligible full-flow configuration with observed "
            "balanced relative utility > 0"
        ),
        "censoring": "not attained is right-censored at the fixed budget",
    }


def empirical_attainment_summary(
    first_rounds: Sequence[int | None], *, budget: int,
    checkpoints: Sequence[int], confidence_z: float = 1.959963984540054,
) -> dict:
    """Estimate target-attainment probability over independent paired cells."""
    if not first_rounds:
        raise ValueError("empirical attainment requires at least one paired cell")
    if any(value is not None and not 1 <= int(value) <= budget
           for value in first_rounds):
        raise ValueError("first-attainment round lies outside the fixed budget")
    if any(not 1 <= int(item) <= budget for item in checkpoints):
        raise ValueError("checkpoints must lie inside the fixed budget")
    count = len(first_rounds)
    rows = {}
    for checkpoint in checkpoints:
        successes = sum(value is not None and int(value) <= int(checkpoint)
                        for value in first_rounds)
        probability = successes / count
        z2 = confidence_z ** 2
        denominator = 1 + z2 / count
        center = (probability + z2 / (2 * count)) / denominator
        radius = (confidence_z * math.sqrt(
            probability * (1 - probability) / count
            + z2 / (4 * count * count)
        ) / denominator)
        rows[str(checkpoint)] = {
            "attained_cells": successes, "cell_count": count,
            "probability": probability,
            "wilson_95_ci": [max(0.0, center - radius), min(1.0, center + radius)],
        }
    return {
        "paired_cell_count": count, "budget": int(budget),
        "checkpoints": rows,
        "unit": "one design-PDK by optimizer-seed cell",
        "target": "first feasible observed configuration with relative utility > 0",
    }


def paired_permutation_test(differences: Iterable[float], *,
                            alternative: str = "greater",
                            monte_carlo_samples: int = 100_000,
                            seed_material: str = "",
                            unit: str = "one paired analysis unit") -> dict:
    values = tuple(float(value) for value in differences)
    if not values or any(not math.isfinite(value) for value in values):
        raise ValueError("paired differences must be non-empty and finite")
    if alternative not in {"greater", "less", "two-sided"}:
        raise ValueError("invalid alternative")
    observed = sum(values) / len(values)
    exact = len(values) <= 20
    if exact:
        signs = itertools.product((-1.0, 1.0), repeat=len(values))
        samples = [sum(sign * value for sign, value in zip(row, values)) / len(values)
                   for row in signs]
    else:
        seed = int(hashlib.sha256(seed_material.encode()).hexdigest()[:16], 16)
        rng = random.Random(seed)
        samples = [sum((1 if rng.getrandbits(1) else -1) * value for value in values)
                   / len(values) for _ in range(monte_carlo_samples)]
    if alternative == "greater":
        extreme = sum(value >= observed for value in samples)
    elif alternative == "less":
        extreme = sum(value <= observed for value in samples)
    else:
        extreme = sum(abs(value) >= abs(observed) for value in samples)
    # Exact enumeration uses the exact tail fraction. The plus-one correction
    # is reserved for sampled Monte Carlo tests, where it prevents a zero
    # estimate without changing the exact test's reference distribution.
    p_value = (extreme / len(samples) if exact
               else (extreme + 1) / (len(samples) + 1))
    return {
        "n_pairs": len(values), "mean_difference": observed,
        "alternative": alternative, "exact": exact,
        "permutations": len(samples), "p_value": p_value,
        "unit": unit,
    }


def holm_adjust(p_values: Mapping[str, float]) -> dict[str, float]:
    rows = sorted((float(value), key) for key, value in p_values.items())
    if any(not 0 <= value <= 1 for value, _ in rows):
        raise ValueError("p-values must lie in [0,1]")
    adjusted = {}; running = 0.0; count = len(rows)
    for rank, (value, key) in enumerate(rows):
        running = max(running, min(1.0, (count - rank) * value))
        adjusted[key] = running
    return adjusted


def paired_bootstrap_interval(differences: Sequence[float], *, samples: int = 10_000,
                              confidence: float = .95,
                              seed_material: str = "") -> dict:
    values = tuple(float(value) for value in differences)
    if not values or not 100 <= samples <= 1_000_000 or not .5 < confidence < 1:
        raise ValueError("invalid paired bootstrap input")
    seed = int(hashlib.sha256(seed_material.encode()).hexdigest()[:16], 16)
    rng = random.Random(seed); count = len(values)
    estimates = sorted(median(values[rng.randrange(count)] for _ in range(count))
                       for _ in range(samples))
    alpha = (1 - confidence) / 2
    low = estimates[int(alpha * (samples - 1))]
    high = estimates[int((1 - alpha) * (samples - 1))]
    return {"median_difference": median(values), "confidence": confidence,
            "samples": samples, "interval": [low, high], "n_pairs": count}


def cliffs_delta(candidate: Sequence[float], baseline: Sequence[float]) -> float:
    left, right = tuple(map(float, candidate)), tuple(map(float, baseline))
    if not left or not right:
        raise ValueError("Cliff delta requires two non-empty groups")
    wins = sum(a > b for a in left for b in right)
    losses = sum(a < b for a in left for b in right)
    return (wins - losses) / (len(left) * len(right))
