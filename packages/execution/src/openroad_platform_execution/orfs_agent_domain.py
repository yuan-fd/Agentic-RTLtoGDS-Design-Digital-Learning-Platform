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

    @classmethod
    def create(cls, *, platform: str, search_parameter_names: Sequence[str],
               admissible_values: Mapping[str, Sequence[Any]], fixed_parameters: Mapping[str, Any]) -> "ORFSAgentDomain":
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
                   admissible_values={name: values[name] for name in sorted(values)}, fixed_parameters=dict(sorted(fixed.items())))

    def to_dict(self) -> dict[str, Any]:
        payload = {"schema_version": 1, "platform": self.platform,
                   "search_parameter_names": list(self.search_parameter_names),
                   "admissible_values": {name: list(values) for name, values in self.admissible_values.items()},
                   "fixed_parameters": self.fixed_parameters,
                   "frozen_constraints": ["clock_period_ns", "clock_uncertainty", "io_delay"]}
        payload["domain_sha256"] = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return payload
