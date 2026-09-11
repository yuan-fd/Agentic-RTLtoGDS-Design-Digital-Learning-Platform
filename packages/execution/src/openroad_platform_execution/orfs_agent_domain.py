"""Typed domains for the pinned external ORFS-Agent adapter.

``ORFSAgentFullDomain`` is the product-facing upstream contract.  It preserves
the complete 12-field domain published by ORFS-Agent.  ``ORFSAgentDomain`` is
the older fixed-timing, eight-field comparison profile; it remains available
only so historical evidence can still be decoded while callers migrate.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


FULL_PARAMETER_NAMES = (
    "CLK", "UTIL", "TNS_End_Percent", "GP_PAD", "DP_PAD", "DPO",
    "PIN_ADJ", "UP_ADJ", "LB_ADDON", "HIER_SYNTH", "CTS_CSIZE", "CTS_CDIA",
)
FULL_OBJECTIVES = ("ECP", "DWL", "COMBO")
_FULL_PROTOCOL_KEYS = {
    "protocol_id", "orfs_agent_commit", "orfs_commit", "design", "platform",
    "objective_set", "seed_policy", "budget", "evaluator", "initialization_method",
    "design_bundle_sha256", "pdk_bundle_sha256", "toolchain_receipt_sha256",
}


SHARED_PARAMETER_NAMES = (
    "core_utilization_pct", "tns_end_percent", "global_placement_padding",
    "detail_placement_padding", "enable_dpo", "place_density_lb_addon",
    "cts_cluster_size", "cts_cluster_diameter",
)
_PLATFORM_UTILIZATION = {"asap7": (30, 75), "sky130hd": (20, 70), "nangate45": (20, 80)}
_RANGES = {
    "tns_end_percent": (0, 100, int), "global_placement_padding": (0, 3, int),
    "detail_placement_padding": (0, 3, int), "enable_dpo": (0, 1, int),
    "place_density_lb_addon": (0.0, 0.5, float), "cts_cluster_size": (10, 40, int),
    "cts_cluster_diameter": (40, 120, int),
}
_HASH = __import__("re").compile(r"^[0-9a-f]{64}$")
_PROTOCOL_KEYS = {"rtl_sha256", "pdk_id", "toolchain_id", "sdc_sha256", "evaluator_version", "seed_policy", "timing"}


def _digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _full_protocol(raw: Mapping[str, Any], *, design: str, platform: str) -> dict[str, Any]:
    """Validate the immutable campaign receipt for full upstream semantics."""
    if set(raw) != _FULL_PROTOCOL_KEYS:
        raise ValueError("full ORFS-Agent experiment protocol has unknown or missing fields")
    if raw.get("design") != design or raw.get("platform") != platform:
        raise ValueError("full ORFS-Agent protocol design/platform mismatch")
    for name in ("protocol_id", "orfs_agent_commit", "orfs_commit", "seed_policy",
                 "evaluator", "initialization_method"):
        if not isinstance(raw.get(name), str) or not raw[name]:
            raise ValueError(f"full ORFS-Agent protocol {name} must be a non-empty string")
    for name in ("design_bundle_sha256", "pdk_bundle_sha256", "toolchain_receipt_sha256"):
        if not isinstance(raw.get(name), str) or not _HASH.fullmatch(raw[name]):
            raise ValueError(f"full ORFS-Agent protocol {name} must be SHA-256")
    objectives = raw.get("objective_set")
    if not isinstance(objectives, (list, tuple)) or tuple(objectives) != FULL_OBJECTIVES:
        raise ValueError("full ORFS-Agent protocol must retain ECP, DWL, and COMBO")
    budget = raw.get("budget")
    required_budget = {"initial_samples", "rounds", "suggestions_per_round", "confirmations"}
    if not isinstance(budget, Mapping) or set(budget) != required_budget:
        raise ValueError("full ORFS-Agent protocol budget is incomplete")
    positive = required_budget - {"confirmations"}
    if (any(isinstance(budget[name], bool) or not isinstance(budget[name], int)
            or budget[name] <= 0 for name in positive)
            or isinstance(budget["confirmations"], bool)
            or not isinstance(budget["confirmations"], int)
            or budget["confirmations"] < 0):
        raise ValueError(
            "full ORFS-Agent protocol execution counts must be positive and "
            "confirmations must be non-negative")
    return {
        **{name: raw[name] for name in sorted(_FULL_PROTOCOL_KEYS - {"objective_set", "budget"})},
        "objective_set": list(FULL_OBJECTIVES),
        "budget": {name: int(budget[name]) for name in sorted(required_budget)},
    }


def _resolved_full_constraints(raw: Mapping[str, Any], *, platform: str) -> dict[str, dict[str, Any]]:
    if platform not in {"asap7", "sky130hd"} or set(raw) != set(FULL_PARAMETER_NAMES):
        raise ValueError("upstream ORFS-Agent constraints do not contain the complete 12-field domain")
    resolved: dict[str, dict[str, Any]] = {}
    for name in FULL_PARAMETER_NAMES:
        entry = raw[name]
        if not isinstance(entry, Mapping):
            raise ValueError(f"upstream constraint {name} must be an object")
        if entry.get("pdk_specific") is True:
            entry = entry.get(platform)
            if not isinstance(entry, Mapping):
                raise ValueError(f"upstream constraint {name} lacks platform {platform}")
        kind = entry.get("type")
        if kind in {"integer", "float"}:
            bounds = entry.get("range")
            if (not isinstance(bounds, list) or len(bounds) != 2
                    or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in bounds)
                    or float(bounds[0]) >= float(bounds[1])):
                raise ValueError(f"upstream constraint {name} has an invalid range")
            resolved[name] = {"type": kind, "range": list(bounds)}
        elif kind == "binary":
            if entry.get("values") != [0, 1]:
                raise ValueError(f"upstream constraint {name} has invalid binary values")
            resolved[name] = {"type": kind, "values": [0, 1]}
        else:
            raise ValueError(f"upstream constraint {name} has unsupported type")
    return resolved


@dataclass(frozen=True)
class ORFSAgentFullDomain:
    """Exact, hash-bound 12-dimensional ORFS-Agent proposal domain."""

    design: str
    platform: str
    constraints: dict[str, dict[str, Any]]
    upstream_constraints_sha256: str
    experiment_protocol: dict[str, Any]

    @classmethod
    def from_upstream(cls, *, source_root: str | Path, design: str, platform: str,
                      experiment_protocol: Mapping[str, Any]) -> "ORFSAgentFullDomain":
        if design not in {"aes", "ibex", "jpeg"}:
            raise ValueError("full ORFS-Agent domain supports the upstream aes/ibex/jpeg designs")
        path = (Path(source_root).expanduser().resolve()
                / "AutoTuner-integration/ORFS-with-AutoTuner/constraints.json")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("upstream ORFS-Agent constraints must be a JSON object")
        return cls(
            design=design,
            platform=platform,
            constraints=_resolved_full_constraints(payload, platform=platform),
            upstream_constraints_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            experiment_protocol=_full_protocol(experiment_protocol, design=design, platform=platform),
        )

    def to_dict(self) -> dict[str, Any]:
        protocol = _full_protocol(self.experiment_protocol, design=self.design, platform=self.platform)
        payload = {
            "schema_version": 2,
            "kind": "upstream-full-12d",
            "design": self.design,
            "platform": self.platform,
            "parameter_names": list(FULL_PARAMETER_NAMES),
            "constraints": self.constraints,
            "upstream_constraints_sha256": self.upstream_constraints_sha256,
            "experiment_protocol": protocol,
            "protocol_sha256": _digest(protocol),
            "variable_clock_semantics": True,
        }
        payload["domain_sha256"] = _digest(payload)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ORFSAgentFullDomain":
        required = {
            "schema_version", "kind", "design", "platform", "parameter_names",
            "constraints", "upstream_constraints_sha256", "experiment_protocol",
            "protocol_sha256", "variable_clock_semantics", "domain_sha256",
        }
        if (set(payload) != required or payload.get("schema_version") != 2
                or payload.get("kind") != "upstream-full-12d"
                or payload.get("parameter_names") != list(FULL_PARAMETER_NAMES)
                or payload.get("variable_clock_semantics") is not True):
            raise ValueError("full ORFS-Agent domain has unknown, missing, or reduced fields")
        canonical = {name: value for name, value in payload.items() if name != "domain_sha256"}
        if payload.get("domain_sha256") != _digest(canonical):
            raise ValueError("full ORFS-Agent domain hash is invalid")
        protocol = _full_protocol(payload["experiment_protocol"], design=str(payload["design"]),
                                  platform=str(payload["platform"]))
        if payload.get("protocol_sha256") != _digest(protocol):
            raise ValueError("full ORFS-Agent protocol hash is invalid")
        constraints = payload.get("constraints")
        if not isinstance(constraints, Mapping) or set(constraints) != set(FULL_PARAMETER_NAMES):
            raise ValueError("full ORFS-Agent domain does not preserve every upstream parameter")
        if not isinstance(payload.get("upstream_constraints_sha256"), str) or not _HASH.fullmatch(
                str(payload["upstream_constraints_sha256"])):
            raise ValueError("full ORFS-Agent constraints hash is invalid")
        # Reuse the same structural checks without pretending the resolved form
        # is the source JSON's PDK-specific wrapper.
        normalized: dict[str, dict[str, Any]] = {}
        for name in FULL_PARAMETER_NAMES:
            entry = constraints[name]
            if not isinstance(entry, Mapping):
                raise ValueError(f"full ORFS-Agent constraint {name} must be an object")
            kind = entry.get("type")
            if kind in {"integer", "float"} and isinstance(entry.get("range"), list) and len(entry["range"]) == 2:
                normalized[name] = {"type": kind, "range": list(entry["range"])}
            elif kind == "binary" and entry.get("values") == [0, 1]:
                normalized[name] = {"type": kind, "values": [0, 1]}
            else:
                raise ValueError(f"full ORFS-Agent constraint {name} is invalid")
        return cls(str(payload["design"]), str(payload["platform"]), normalized,
                   str(payload["upstream_constraints_sha256"]), protocol)

    @property
    def protocol_sha256(self) -> str:
        return _digest(self.experiment_protocol)

    def validate_candidate(self, candidate: Mapping[str, Any]) -> None:
        # JSON/SQLite canonical serializers may sort object keys.  Feature
        # order is carried explicitly by ``parameter_names`` and restored by
        # task/adaptor builders; object insertion order is not an integrity
        # boundary.
        if set(candidate) != set(FULL_PARAMETER_NAMES):
            raise ValueError("candidate must preserve all 12 upstream ORFS-Agent parameters")
        for name in FULL_PARAMETER_NAMES:
            raw, rule = candidate[name], self.constraints[name]
            if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(float(raw)):
                raise ValueError(f"candidate {name} must be finite numeric data")
            if rule["type"] in {"integer", "binary"} and int(raw) != raw:
                raise ValueError(f"candidate {name} must be an integer")
            if rule["type"] == "binary" and int(raw) not in rule["values"]:
                raise ValueError(f"candidate {name} is outside upstream values")
            if rule["type"] != "binary" and not float(rule["range"][0]) <= float(raw) <= float(rule["range"][1]):
                raise ValueError(f"candidate {name} is outside upstream range")

    def validate_observation(self, observation: Mapping[str, Any]) -> None:
        if observation.get("protocol_sha256") != self.protocol_sha256:
            raise ValueError("observation does not match the full ORFS-Agent protocol")
        candidate = observation.get("candidate")
        metrics = observation.get("metrics")
        if not isinstance(candidate, Mapping) or not isinstance(metrics, Mapping):
            raise ValueError("full ORFS-Agent observation requires candidate and metrics")
        self.validate_candidate(candidate)


def _protocol(raw: Mapping[str, Any]) -> dict[str, Any]:
    if set(raw) != _PROTOCOL_KEYS:
        raise ValueError("experiment protocol has unknown or missing fields")
    if not all(isinstance(raw[name], str) and raw[name] for name in _PROTOCOL_KEYS - {"timing", "rtl_sha256", "sdc_sha256"}):
        raise ValueError("experiment protocol identifiers must be non-empty strings")
    if not all(isinstance(raw[name], str) and _HASH.fullmatch(raw[name]) for name in ("rtl_sha256", "sdc_sha256")):
        raise ValueError("experiment protocol hashes must be SHA-256 values")
    timing = raw["timing"]
    if not isinstance(timing, Mapping) or set(timing) != {"clock_period_ns", "clock_uncertainty_ns", "io_delay_ns"}:
        raise ValueError("experiment protocol timing is incomplete")
    if any(isinstance(timing[name], bool) or not isinstance(timing[name], (int, float)) for name in timing):
        raise ValueError("experiment protocol timing is invalid")
    normalized = {name: float(timing[name]) for name in timing}
    if not all(math.isfinite(value) for value in normalized.values()) or normalized["clock_period_ns"] <= 0 or min(normalized.values()) < 0:
        raise ValueError("experiment protocol timing is invalid")
    return {**{name: raw[name] for name in sorted(_PROTOCOL_KEYS - {"timing"})}, "timing": normalized}


def _canonical(name: str, raw: Any, *, platform: str) -> int | float:
    if name == "core_utilization_pct":
        lower, upper, kind = (*_PLATFORM_UTILIZATION.get(platform, (20, 80)), int)
    else:
        try:
            lower, upper, kind = _RANGES[name]
        except KeyError as exc:
            raise ValueError(f"ORFS-Agent domain does not allow {name}") from exc
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(float(raw)):
        raise ValueError(f"{name} must be a finite number")
    value = kind(raw)
    if value != raw or not lower <= value <= upper:
        raise ValueError(f"{name} is outside its admitted range")
    return value


@dataclass(frozen=True)
class ORFSAgentDomain:
    """A complete, allowlisted, non-timing domain for one native invocation."""
    platform: str
    search_parameter_names: tuple[str, ...]
    admissible_values: dict[str, tuple[int | float, ...]]
    fixed_parameters: dict[str, int | float]
    experiment_protocol: dict[str, Any]

    @classmethod
    def create(cls, *, platform: str, search_parameter_names: Sequence[str],
               admissible_values: Mapping[str, Sequence[Any]], fixed_parameters: Mapping[str, Any],
               experiment_protocol: Mapping[str, Any]) -> "ORFSAgentDomain":
        if platform not in _PLATFORM_UTILIZATION:
            raise ValueError("ORFS-Agent platform is not allowlisted")
        names = tuple(str(name) for name in search_parameter_names)
        if not platform or not names or len(names) != len(set(names)):
            raise ValueError("platform and distinct search parameter names are required")
        if set(names) - set(SHARED_PARAMETER_NAMES):
            raise ValueError("ORFS-Agent domain has unsupported search parameters")
        if set(admissible_values) != set(names):
            raise ValueError("admissible_values must define every and only search parameter")
        if set(fixed_parameters) & set(names) or set(fixed_parameters) - set(SHARED_PARAMETER_NAMES):
            raise ValueError("fixed parameters must be disjoint allowlisted names")
        if set(names) | set(fixed_parameters) != set(SHARED_PARAMETER_NAMES):
            raise ValueError("every shared parameter must be searched or fixed")
        values: dict[str, tuple[int | float, ...]] = {}
        for name in names:
            raw_values = admissible_values[name]
            if isinstance(raw_values, (str, bytes)) or not isinstance(raw_values, Sequence):
                raise ValueError(f"{name} admissible values must be a sequence")
            normalized = tuple(dict.fromkeys(_canonical(name, raw, platform=platform) for raw in raw_values))
            if len(normalized) < 2:
                raise ValueError(f"{name} needs at least two distinct admissible values")
            values[name] = normalized
        fixed = {name: _canonical(name, raw, platform=platform) for name, raw in fixed_parameters.items()}
        # Do not represent an illegal Cartesian relation. A later optimizer can
        # search either padding knob while the other remains frozen.
        if {"global_placement_padding", "detail_placement_padding"} <= set(names):
            raise ValueError("padding relation requires global or detail padding to be fixed")
        gp = fixed.get("global_placement_padding")
        dp = fixed.get("detail_placement_padding")
        if gp is not None and dp is not None and dp > gp:
            raise ValueError("detail_placement_padding cannot exceed global_placement_padding")
        if gp is not None and "detail_placement_padding" in values and any(value > gp for value in values["detail_placement_padding"]):
            raise ValueError("detail padding values exceed fixed global padding")
        if dp is not None and "global_placement_padding" in values and any(value < dp for value in values["global_placement_padding"]):
            raise ValueError("global padding values are below fixed detail padding")
        return cls(platform=platform, search_parameter_names=tuple(sorted(names)),
                   admissible_values={name: values[name] for name in sorted(values)}, fixed_parameters=dict(sorted(fixed.items())),
                   experiment_protocol=_protocol(experiment_protocol))

    def to_dict(self) -> dict[str, Any]:
        protocol = _protocol(self.experiment_protocol)
        payload = {"schema_version": 1, "platform": self.platform,
                   "search_parameter_names": list(self.search_parameter_names),
                   "admissible_values": {name: list(values) for name, values in self.admissible_values.items()},
                   "fixed_parameters": self.fixed_parameters,
                   "experiment_protocol": protocol, "protocol_sha256": _digest(protocol),
                   "frozen_constraints": ["clock_period_ns", "clock_uncertainty_ns", "io_delay_ns"]}
        payload["domain_sha256"] = _digest(payload)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ORFSAgentDomain":
        required = {"schema_version", "platform", "search_parameter_names", "admissible_values", "fixed_parameters",
                    "experiment_protocol", "protocol_sha256", "frozen_constraints", "domain_sha256"}
        if set(payload) != required or payload.get("schema_version") != 1:
            raise ValueError("ORFS-Agent domain has unknown or missing fields")
        canonical = {key: value for key, value in payload.items() if key != "domain_sha256"}
        if payload.get("domain_sha256") != _digest(canonical):
            raise ValueError("ORFS-Agent domain hash is invalid")
        protocol = _protocol(payload["experiment_protocol"])
        if payload.get("protocol_sha256") != _digest(protocol):
            raise ValueError("ORFS-Agent protocol hash is invalid")
        if payload.get("frozen_constraints") != ["clock_period_ns", "clock_uncertainty_ns", "io_delay_ns"]:
            raise ValueError("ORFS-Agent frozen constraints are invalid")
        return cls.create(platform=str(payload["platform"]), search_parameter_names=payload["search_parameter_names"],
                          admissible_values=payload["admissible_values"], fixed_parameters=payload["fixed_parameters"],
                          experiment_protocol=protocol)

    def validate_observation(self, observation: Mapping[str, Any]) -> None:
        if observation.get("protocol_sha256") != _digest(self.experiment_protocol):
            raise ValueError("observation does not match the frozen experiment protocol")
        parameters = observation.get("parameters")
        if not isinstance(parameters, Mapping) or set(parameters) != set(SHARED_PARAMETER_NAMES) | {"clock_period_ns"}:
            raise ValueError("observation must contain exactly the frozen clock and shared parameter domain")
        if (isinstance(parameters["clock_period_ns"], bool) or not isinstance(parameters["clock_period_ns"], (int, float))
                or float(parameters["clock_period_ns"]) != self.experiment_protocol["timing"]["clock_period_ns"]):
            raise ValueError("observation clock does not match the frozen experiment protocol")
        for name in SHARED_PARAMETER_NAMES:
            value = _canonical(name, parameters[name], platform=self.platform)
            if name in self.fixed_parameters and value != self.fixed_parameters[name]:
                raise ValueError("observation fixed parameter differs from its domain")
            if name in self.admissible_values and value not in self.admissible_values[name]:
                raise ValueError("observation search parameter is outside its domain")
