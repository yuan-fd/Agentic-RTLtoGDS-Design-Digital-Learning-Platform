#!/usr/bin/env python3
"""Bounded, fixed-seed Random control proposal adapter.

The adapter cannot launch ORFS, read QoR, edit benchmarks, or choose a winner.
It only samples a declared finite domain without replacement and emits raw
candidate artifacts for Runtime to execute and the protected evaluator to
measure.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str,
    ).encode()).hexdigest()


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def _result(*, status: str, code: int, started: str, artifacts: list[dict[str, str]],
            provenance: Mapping[str, Any], failure: Mapping[str, str] | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1, "status": status, "exit_code": code,
        "started_at": started, "ended_at": _now(), "metrics": [], "artifacts": artifacts,
        "failure": failure, "provenance": dict(provenance),
    }


def _propose(inputs: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if inputs.get("mode") != "propose":
        raise ValueError("seeded Random control only supports propose mode")
    names = inputs.get("search_parameter_names")
    fixed = inputs.get("fixed_parameters")
    values = inputs.get("admissible_values")
    excluded = inputs.get("excluded_parameter_fingerprints")
    count, seed = inputs.get("n_suggestions"), inputs.get("seed")
    if (not isinstance(names, list) or not names or len(set(names)) != len(names)
            or not isinstance(fixed, Mapping) or not isinstance(values, Mapping)
            or set(values) != set(names) or not isinstance(excluded, list)
            or not isinstance(count, int) or not 1 <= count <= 64
            or not isinstance(seed, int) or seed < 0):
        raise ValueError("invalid Random-control proposal request")
    value_lists: list[list[Any]] = []
    for name in names:
        raw = values[name]
        if not isinstance(raw, list) or len(raw) < 2:
            raise ValueError(f"invalid admissible values for {name}")
        value_lists.append(list(dict.fromkeys(raw)))
    excluded_set = {str(item) for item in excluded}
    legal: list[dict[str, Any]] = []
    for combination in itertools.product(*value_lists):
        parameters = {**dict(fixed), **dict(zip(names, combination))}
        # The task builder has already canonicalized the domain.  This digest
        # exactly matches its shared parameter-vector fingerprint.
        fingerprint = _json_digest(dict(sorted(parameters.items())))
        if fingerprint not in excluded_set:
            legal.append(parameters)
    if len(legal) < count:
        raise ValueError(
            f"frozen domain has only {len(legal)} unseen legal vectors; request needs {count}; no replacement is permitted"
        )
    random.Random(seed).shuffle(legal)
    domain_digest = _json_digest({"names": names, "fixed": dict(fixed), "values": dict(values)})
    candidates = [
        {
            "candidate_id": f"seeded-random-{seed}-{index:04d}",
            "platform_parameters": parameters,
            "sampling": {
                "algorithm": "uniform_without_replacement_over_finite_admitted_domain",
                "seed": seed, "domain_digest": domain_digest,
                "excluded_coordinate_count": len(excluded_set),
            },
        }
        for index, parameters in enumerate(legal[:count])
    ]
    trace = {
        "kind": "seeded-random-control-trace-v1", "algorithm": "uniform_without_replacement",
        "seed": seed, "domain_digest": domain_digest, "domain_cardinality": len(legal) + len(excluded_set),
        "available_unseen_cardinality": len(legal), "proposal_count": len(candidates),
        "qor_access": False,
    }
    return candidates, trace


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    started = _now()
    try:
        request = json.loads(args.request.read_text(encoding="utf-8"))
        task = request.get("task")
        if not isinstance(task, Mapping) or not isinstance(task.get("inputs"), Mapping):
            raise ValueError("Runtime request lacks task inputs")
        candidates, trace = _propose(task["inputs"])
        root = args.result.parent
        candidates_path, input_path, trace_path = (
            root / "optimizer_candidates.json", root / "optimizer_input_manifest.json", root / "optimizer_trace.json",
        )
        _write(candidates_path, {"candidates": candidates})
        _write(input_path, {"task_id": task.get("task_id"), "inputs": task["inputs"]})
        _write(trace_path, trace)
        result = _result(
            status="succeeded", code=0, started=started,
            artifacts=[
                {"kind": "optimizer_candidates", "path": candidates_path.name},
                {"kind": "optimizer_input_manifest", "path": input_path.name},
                {"kind": "optimizer_trace", "path": trace_path.name},
            ],
            provenance={"adapter": "seeded-random-control", "version": "1.0.0", "qor_access": False},
        )
        _write(args.result, result)
        return 0
    except Exception as exc:
        _write(args.result, _result(
            status="failed", code=1, started=started, artifacts=[],
            provenance={"adapter": "seeded-random-control", "version": "1.0.0", "qor_access": False},
            failure={"category": type(exc).__name__, "message": str(exc)},
        ))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
