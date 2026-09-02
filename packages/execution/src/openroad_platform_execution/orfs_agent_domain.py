"""Typed, subtractive transport domain for the external ORFS-Agent adapter."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


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
