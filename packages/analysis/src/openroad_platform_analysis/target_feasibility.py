"""Evidence-only target-design feasibility-domain construction.

This module has one intentionally narrow job: turn repeated, protected
evaluator observations around a frozen anchor into a *subtractive* search
domain.  It is not an optimiser, does not predict QoR, and never turns an
infrastructure failure into a feasible observation.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


def build_anchor_perturbation_plan(
    *, anchor: Mapping[str, Any], levels: Mapping[str, Sequence[Any]],
    seeds: Sequence[int],
) -> list[dict[str, Any]]:
    """Create deterministic one-factor configurations plus paired replicas.

    Every configuration differs from ``anchor`` in at most one parameter.
    Values equal to the anchor are deduplicated into one explicit baseline.
    This makes the preflight evidence interpretable and prevents it from
    accidentally becoming a hidden multi-parameter optimiser.
    """
    if not anchor or not levels:
        raise ValueError("anchor and parameter levels are required")
    if not seeds or len(set(seeds)) != len(seeds) or any(int(seed) < 0 for seed in seeds):
        raise ValueError("seeds must be unique non-negative integers")
    unknown = sorted(set(levels) - set(anchor))
    if unknown:
        raise ValueError(f"levels contain parameters absent from anchor: {', '.join(unknown)}")

    configurations: list[tuple[str | None, Any | None, dict[str, Any]]] = [
        (None, None, dict(anchor))
    ]
    seen = {_digest(dict(anchor))}
    for parameter in sorted(levels):
        values = list(dict.fromkeys(levels[parameter]))
        if not values:
            raise ValueError(f"parameter {parameter} has no planned levels")
        for value in values:
            configuration = {**anchor, parameter: value}
            fingerprint = _digest(configuration)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            configurations.append((parameter, value, configuration))

    cases: list[dict[str, Any]] = []
    for configuration_index, (parameter, value, configuration) in enumerate(configurations):
        fingerprint = _digest(configuration)[:12]
        for seed in seeds:
            cases.append({
                "case_id": f"anchor-{configuration_index:03d}-s{int(seed)}-{fingerprint}",
                "configuration_id": f"target-anchor-{fingerprint}",
                "kind": "baseline" if parameter is None else "one_factor",
                "parameter": parameter,
                "requested_value": value,
                "parameters": dict(sorted(configuration.items())),
                "or_seed": int(seed),
            })
    return cases


def aggregate_target_feasibility(
    *, anchor: Mapping[str, Any], cases: Sequence[Mapping[str, Any]],
    outcomes: Mapping[str, Mapping[str, Any]], required_seeds: Sequence[int],
) -> dict[str, Any]:
    """Build a subtractive domain only from all-replica feasible evidence."""
    expected_seeds = tuple(int(seed) for seed in required_seeds)
    if not expected_seeds or len(set(expected_seeds)) != len(expected_seeds):
        raise ValueError("required_seeds must be unique and non-empty")
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    evaluated = []
    for case in cases:
        case_id = str(case["case_id"])
        result = dict(outcomes.get(case_id) or {})
        row = {**dict(case), "outcome": result}
        evaluated.append(row)
        grouped[str(case["configuration_id"])].append(row)

    configurations = []
    for configuration_id, rows in sorted(grouped.items()):
        seeds = {int(row["or_seed"]) for row in rows}
        all_terminal = all(str(row["outcome"].get("status")) in {"succeeded", "failed", "cancelled", "timed_out", "lost"}
                           for row in rows)
        all_feasible = (
            seeds == set(expected_seeds)
            and all(str(row["outcome"].get("status")) == "succeeded"
                    and row["outcome"].get("evaluator_feasible") is True
                    for row in rows)
        )
        exemplar = rows[0]
        configurations.append({
            "configuration_id": configuration_id,
            "kind": exemplar["kind"],
            "parameter": exemplar["parameter"],
            "requested_value": exemplar["requested_value"],
            "parameters": exemplar["parameters"],
            "replicas_expected": list(expected_seeds),
            "replicas_observed": sorted(seeds),
            "all_terminal": all_terminal,
            "replicated_feasible": all_feasible,
            "case_ids": [str(row["case_id"]) for row in rows],
        })

    baseline = next((row for row in configurations if row["kind"] == "baseline"), None)
    if baseline is None or not baseline["replicated_feasible"]:
        raise ValueError("target feasibility requires a replicated feasible anchor baseline")

    by_parameter: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in configurations:
        parameter = row["parameter"]
        if parameter is not None:
            by_parameter[str(parameter)].append(row)
    dimensions = []
    fixed = {}
    for parameter in sorted(anchor):
        feasible_values = {anchor[parameter]}
        evidence = by_parameter.get(parameter, [])
        for row in evidence:
            if row["replicated_feasible"]:
                feasible_values.add(row["requested_value"])
        ordered = sorted(feasible_values)
        # A dimension needs more than the anchor point.  Otherwise it stays
        # explicitly fixed rather than being sampled on wishful extrapolation.
        if len(ordered) >= 2:
            dimensions.append({
                "parameter": parameter,
                "observed_feasible_values": ordered,
                "lower": ordered[0], "upper": ordered[-1],
                "evidence_configuration_ids": [
                    row["configuration_id"] for row in evidence
                    if row["replicated_feasible"]
                ],
            })
        else:
            fixed[parameter] = anchor[parameter]

    value = {
        "schema_version": 1,
        "protocol": "target-anchor-one-factor-three-replica-v1",
        "required_seeds": list(expected_seeds),
        "anchor": dict(sorted(anchor.items())),
        "configuration_count": len(configurations),
        "case_count": len(evaluated),
        "configurations": configurations,
        "dimensions": dimensions,
        "fixed_parameters": dict(sorted(fixed.items())),
        "claim_boundary": (
            "A dimension has repeated one-factor feasibility evidence around the frozen "
            "anchor. This is a subtractive execution domain, not proof that arbitrary "
            "multi-parameter combinations are feasible or QoR-improving."
        ),
    }
    return {**value, "domain_digest": _digest(value)}


def derive_admitted_target_domain(report: Mapping[str, Any], *,
                                  required_parameters: Sequence[str]) -> dict[str, Any]:
    """Validate and normalize a preflight report for a later L2 campaign.

    The resulting object does not widen an observed value set.  Parameters
    without at least two repeated-feasible values are fixed at the anchor.
    Consumers may generate combinations, but must retain the report digest
    because one-factor feasibility is not a blanket combination guarantee.
    """
    if report.get("protocol") != "target-anchor-one-factor-three-replica-v1":
        raise ValueError("unsupported target-feasibility protocol")
    anchor = report.get("anchor")
    dimensions = report.get("dimensions")
    fixed = report.get("fixed_parameters")
    if not isinstance(anchor, Mapping) or not isinstance(dimensions, list) or not isinstance(fixed, Mapping):
        raise ValueError("target-feasibility report is structurally incomplete")
    required = tuple(str(name) for name in required_parameters)
    if not required or len(set(required)) != len(required):
        raise ValueError("required parameters must be unique and non-empty")
    if not set(required) <= set(anchor):
        raise ValueError("target-feasibility anchor lacks required shared parameters")
    observed: dict[str, list[Any]] = {}
    for row in dimensions:
        if not isinstance(row, Mapping):
            raise ValueError("target-feasibility dimension must be an object")
        name = str(row.get("parameter") or "")
        values = row.get("observed_feasible_values")
        if name not in required or not isinstance(values, list) or len(values) < 2:
            raise ValueError("target-feasibility dimension is invalid")
        if name in observed:
            raise ValueError("target-feasibility dimension is duplicated")
        observed[name] = list(values)
    if set(observed) & set(fixed):
        raise ValueError("target-feasibility dimension overlaps fixed parameter")
    if set(observed) | set(fixed) != set(anchor):
        raise ValueError("target-feasibility report does not partition its full flow anchor")
    for name, value in fixed.items():
        if anchor.get(name) != value:
            raise ValueError("fixed target-feasibility value differs from frozen anchor")
    expected = report.get("domain_digest")
    unsigned = {key: value for key, value in report.items() if key != "domain_digest"}
    if not isinstance(expected, str) or _digest(unsigned) != expected:
        raise ValueError("target-feasibility report digest mismatch")
    shared_fixed = {name: fixed[name] for name in required if name not in observed}
    return {
        "schema_version": 1,
        "kind": "admitted-target-feasibility-domain",
        "source_domain_digest": expected,
        "search_parameter_names": sorted(observed),
        "admissible_values": {name: observed[name] for name in sorted(observed)},
        "fixed_parameters": dict(sorted(shared_fixed.items())),
        "flow_anchor": dict(sorted(anchor.items())),
        "fixed_nonshared_flow_parameters": {
            name: fixed[name] for name in sorted(set(fixed) - set(required))
        },
        "claim_boundary": report["claim_boundary"],
    }


def derive_target_execution_envelope(
    report: Mapping[str, Any], *, required_parameters: Sequence[str],
    interpolated_steps: Mapping[str, str | float | int],
) -> dict[str, Any]:
    """Create a bounded execution envelope without inflating feasibility claims.

    The source report proves repeated one-factor feasibility only at its
    observed values.  An interpolated point is therefore merely a typed,
    finite candidate for the protected evaluator; it is not relabelled as a
    preflight-feasible combination.  Any failed point remains evidence.
    """
    admitted = derive_admitted_target_domain(report, required_parameters=required_parameters)
    if not interpolated_steps:
        raise ValueError("execution envelope requires an explicit interpolation step")
    verified = {name: list(values) for name, values in admitted["admissible_values"].items()}
    execution = {name: list(values) for name, values in verified.items()}
    derivations: dict[str, dict[str, Any]] = {}
    for name, raw_step in sorted(interpolated_steps.items()):
        if name not in verified:
            raise ValueError(f"execution-envelope interpolation requires an observed dimension: {name}")
        values = verified[name]
        if len(values) < 2:
            raise ValueError(f"execution-envelope interpolation needs two verified endpoints: {name}")
        try:
            lower, upper, step = Decimal(str(values[0])), Decimal(str(values[-1])), Decimal(str(raw_step))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"execution-envelope interpolation is not numeric: {name}") from exc
        if step <= 0 or upper <= lower:
            raise ValueError(f"execution-envelope interpolation has invalid bounds: {name}")
        quotient = (upper - lower) / step
        if quotient != quotient.to_integral_value():
            raise ValueError(f"execution-envelope step does not tile verified interval: {name}")
        count = int(quotient) + 1
        if count > 100_000:
            raise ValueError(f"execution-envelope interpolation is unbounded: {name}")
        execution[name] = [float(lower + step * index) for index in range(count)]
        derivations[name] = {
            "kind": "bounded_numeric_interpolation",
            "verified_endpoints": [values[0], values[-1]],
            "step": str(step),
            "execution_value_count": count,
            "not_preflight_feasible_claim": True,
        }
    value = {
        "schema_version": 1,
        "kind": "target-execution-envelope-v1",
        "source_domain_digest": admitted["source_domain_digest"],
        "source_preflight_protocol": report["protocol"],
        "search_parameter_names": admitted["search_parameter_names"],
        "verified_values": {name: verified[name] for name in sorted(verified)},
        "admissible_values": {name: execution[name] for name in sorted(execution)},
        "fixed_parameters": admitted["fixed_parameters"],
        "flow_anchor": admitted["flow_anchor"],
        "fixed_nonshared_flow_parameters": admitted["fixed_nonshared_flow_parameters"],
        "execution_value_derivations": derivations,
        "claim_boundary": (
            "Execution-envelope points satisfy the typed platform contract and share the "
            "frozen evaluator, but only verified_values have repeated one-factor feasibility "
            "evidence. Interpolated points are not claimed feasible until their own protected "
            "evaluator result is recorded; failures are retained."
        ),
    }
    return {**value, "envelope_digest": _digest(value)}
