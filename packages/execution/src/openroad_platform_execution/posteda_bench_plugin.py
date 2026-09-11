"""Typed Runtime boundary for the pinned PostEDA-Bench diagnostic evaluator."""

from __future__ import annotations

import hashlib
import os
import platform
import sys
import uuid
from pathlib import Path

from openroad_platform_contracts import (
    PluginManifest, PostEDADiagnosisPrediction, TaskSpec,
)


POSTEDA_BENCH_PLUGIN_ID = "posteda-bench"
POSTEDA_BENCH_PLUGIN_VERSION = "51884e5f"
POSTEDA_BENCH_UPSTREAM_COMMIT = "51884e5f20e6e199219cec87c1c779a3dfab95bc"
POSTEDA_BENCH_PUBLIC_CAPABILITY = "benchmark.posteda.public-case"
POSTEDA_BENCH_EVALUATE_CAPABILITY = "benchmark.posteda.evaluate-diagnosis"
POSTEDA_BENCH_ID = "posteda-bench-51884e5"
POSTEDA_ADMITTED_TASKS = ("drc_essential/L1/q1",)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_posteda_public_case_task(
    *, project_id: str, task_id: str, runtime_task_id: str | None = None,
    timeout_seconds: int = 180,
) -> TaskSpec:
    if task_id not in POSTEDA_ADMITTED_TASKS:
        raise ValueError("PostEDA task is outside the admitted bounded sample")
    task = TaskSpec(
        task_id=runtime_task_id or f"posteda-public-{uuid.uuid4().hex}",
        project_id=project_id, design_id="posteda-drc-q1",
        plugin_id=POSTEDA_BENCH_PLUGIN_ID,
        inputs={"mode": "public_case", "benchmark_id": POSTEDA_BENCH_ID,
                "task_id": task_id},
        parameters={"parser": "upstream-klayout-report"},
        timeout_seconds=timeout_seconds, max_attempts=1,
        expected_artifacts=("benchmark_public_case", "benchmark_native_trace"),
        labels={"capability": POSTEDA_BENCH_PUBLIC_CAPABILITY,
                "hidden_label_access": "denied",
                "benchmark_scope": "one-drc-diagnostic-task"},
    )
    task.validate()
    return task


def build_posteda_evaluation_task(
    *, project_id: str, prediction: PostEDADiagnosisPrediction,
    runtime_task_id: str | None = None, timeout_seconds: int = 60,
) -> TaskSpec:
    if not isinstance(prediction, PostEDADiagnosisPrediction):
        raise TypeError("PostEDA evaluation requires a typed diagnosis prediction")
    prediction.validate()
    if prediction.task_id not in POSTEDA_ADMITTED_TASKS:
        raise ValueError("PostEDA task is outside the admitted bounded sample")
    task = TaskSpec(
        task_id=runtime_task_id or f"posteda-score-{uuid.uuid4().hex}",
        project_id=project_id, design_id="posteda-drc-q1",
        plugin_id=POSTEDA_BENCH_PLUGIN_ID,
        inputs={"mode": "evaluate_diagnosis", "benchmark_id": POSTEDA_BENCH_ID,
                "task_id": prediction.task_id,
                "prediction": prediction.to_dict()},
        parameters={"score_protocol": "derived-diagnostic-v1"},
        timeout_seconds=timeout_seconds, max_attempts=1,
        expected_artifacts=("benchmark_diagnosis_score",
                            "benchmark_evaluation_trace"),
        labels={"capability": POSTEDA_BENCH_EVALUATE_CAPABILITY,
                "official_metric": "false", "hidden_label_role": "scorer-only"},
    )
    task.validate()
    return task


def posteda_bench_plugin_manifest(
    *, source_checkout: str | Path, klayout_executable: str | Path,
    python_executable: str | Path = sys.executable,
    default_timeout_seconds: int = 180,
) -> PluginManifest:
    source = Path(source_checkout).expanduser().resolve()
    klayout = Path(klayout_executable).expanduser().resolve()
    python = Path(python_executable).expanduser().absolute()
    if not source.is_dir() or not klayout.is_file() or not python.is_file():
        raise FileNotFoundError("PostEDA checkout, KLayout and Python are required")
    repository = Path(__file__).resolve().parents[4]
    adapter = repository / "integrations/posteda_bench/posteda_bench_adapter.py"
    lock = repository / "integrations/posteda_bench/source.lock.json"
    if not adapter.is_file() or not lock.is_file():
        raise FileNotFoundError("PostEDA adapter or source lock is missing")
    manifest = PluginManifest(
        plugin_id=POSTEDA_BENCH_PLUGIN_ID,
        plugin_version=POSTEDA_BENCH_PLUGIN_VERSION,
        adapter_entry=(str(python), str(adapter)),
        capabilities=(POSTEDA_BENCH_PUBLIC_CAPABILITY,
                      POSTEDA_BENCH_EVALUATE_CAPABILITY),
        supported_arch=(platform.machine(),),
        input_schema={"type": "object", "additionalProperties": False,
                      "required": ["mode", "benchmark_id", "task_id"]},
        output_schema={"type": "object",
                       "required": ["status", "artifacts", "provenance"]},
        required_tools=("git", "klayout"),
        default_timeout_seconds=default_timeout_seconds,
        artifact_rules=tuple({"kind": kind, "required": False} for kind in (
            "benchmark_public_case", "benchmark_native_trace",
            "benchmark_diagnosis_score", "benchmark_evaluation_trace")),
        environment={
            "POSTEDA_BENCH_SOURCE": str(source),
            "POSTEDA_BENCH_KLAYOUT": str(klayout),
            "POSTEDA_BENCH_SOURCE_LOCK": str(lock),
            "POSTEDA_BENCH_SOURCE_LOCK_SHA256": _sha256(lock),
            "PYTHONDONTWRITEBYTECODE": "1",
            "NO_PROXY": "*", "no_proxy": "*",
            "PATH": os.pathsep.join((str(klayout.parent), str(python.parent),
                                     "/usr/bin", "/bin")),
        },
    )
    manifest.validate()
    return manifest
