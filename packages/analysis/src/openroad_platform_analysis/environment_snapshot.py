"""Immutable Python dependency evidence for reproducible DSE campaigns."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
from typing import Iterable


OPTIMIZATION_DISTRIBUTIONS = (
    "numpy", "scipy", "torch", "gpytorch", "botorch", "optuna",
    "ray", "hyperopt",
)


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


def current_python_environment(
    distributions: Iterable[str] = OPTIMIZATION_DISTRIBUTIONS,
) -> dict:
    packages = {}
    for name in distributions:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    value = {
        "schema_version": 1,
        "kind": "python-optimization-environment",
        "python_version": ".".join(map(str, sys.version_info[:3])),
        "python_implementation": sys.implementation.name,
        "executable": str(Path(sys.executable).resolve()),
        "distributions": packages,
    }
    return {**value, "fingerprint": _digest(value)}


def external_python_environment(
    python: str | Path,
    distributions: Iterable[str] = OPTIMIZATION_DISTRIBUTIONS,
) -> dict:
    executable = str(Path(python).expanduser().absolute())
    names = list(distributions)
    source = (
        "import importlib.metadata,json,pathlib,sys\n"
        f"names={names!r}\n"
        "versions={}\n"
        "for name in names:\n"
        " try: versions[name]=importlib.metadata.version(name)\n"
        " except importlib.metadata.PackageNotFoundError: versions[name]=None\n"
        "print(json.dumps({'python_version':'.'.join(map(str,sys.version_info[:3])),"
        "'python_implementation':sys.implementation.name,"
        "'executable':str(pathlib.Path(sys.executable).resolve()),"
        "'distributions':versions},sort_keys=True))\n"
    )
    completed = subprocess.run(
        [executable, "-c", source], text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False, timeout=60,
    )
    if completed.returncode:
        raise ValueError(
            f"external Python environment query failed: {completed.stderr[:300]}")
    observed = json.loads(completed.stdout)
    value = {
        "schema_version": 1,
        "kind": "external-python-optimization-environment",
        **observed,
        "invoked_executable": executable,
    }
    return {**value, "fingerprint": _digest(value)}


def combined_python_environment(*, controller: dict, external: dict | None = None) -> dict:
    value = {
        "schema_version": 1,
        "kind": "combined-python-optimization-environment",
        "controller": controller,
        "external": external,
    }
    return {**value, "fingerprint": _digest(value)}
