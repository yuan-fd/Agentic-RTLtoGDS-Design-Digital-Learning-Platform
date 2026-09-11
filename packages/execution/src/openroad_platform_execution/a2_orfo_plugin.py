"""Typed admission boundary for the pinned external A2-ORFO policy.

The module owns no optimiser.  It validates the upstream source/model and
constructs the immutable policy request consumed by the attempt-isolated
adapter in ``integrations/a2_orfo``.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from openroad_platform_contracts import PluginManifest, TaskSpec


A2_ORFO_PLUGIN_ID = "a2-orfo"
A2_ORFO_PLUGIN_VERSION = "2026.06.23"
A2_ORFO_UPSTREAM_COMMIT = "8b20a3c1f22934a39c7ba51ed0ec6dffe730da2d"
A2_ORFO_UPSTREAM_TREE = "b3906db597359f5786e6cfc69f308479e26f5800"
A2_ORFO_MODEL_COMMIT = "b33106f585b9ce46904ad7443a3b52b7a63e231c"
A2_ORFO_MODEL_TREE_SHA256 = "feeb00c02e146d3a09d8b825af77224c2bbcc158bd5e2a5dbb18c3904d067f26"
A2_ORFO_PARAMETERS = (
    "UTIL", "GP_PAD", "DP_PAD", "HIER_SYNTH", "PIN_ADJ", "UP_ADJ",
    "TNS_End_Percent", "LB_ADDON", "CTS_CSIZE", "CTS_CDIA", "DPO", "CLK",
)
A2_ORFO_OBJECTIVES = ("ECP", "DWL", "COMBO")
_HASHES = {
    "optimize.py": "01d3ac68abf03880c6b9b2bf6e6db5484ab247314a2df0643f865c3565a14ad5",
    "constraint_optimizer.py": "0b891e70c4c80b390909795281a6a786e29ece9175dfe52c99d130b1d4d10ceb",
    "inspectfuncs.py": "39179bf246a2b0a9cd7d950ec9c52c5392fc8c1c38aa0434a001cf1c7dc00cfb",
    "modelfuncs.py": "342307d8efbf60bed755aa137dc9ec07c097da69ee81d549e3498d65bc7fc60d",
    "prompts.py": "7edc2d26739324128623b7dcb5e0e5a3956ab8ea191b5ddeff5263624a38e852",
    "AutoTuner-integration/ORFS-with-AutoTuner/constraints.json":
        "9de2da8058266f8287b153a06ecafbc3698281b24ea226f9e72e458336dcf7ad",
}
_PROTOCOL_KEYS = {
    "protocol_id", "a2_orfo_commit", "orfs_executor_commit", "design", "platform",
    "objective_set", "seed_policy", "budget", "evaluator", "objective_baselines",
    "design_bundle_sha256", "pdk_bundle_sha256", "toolchain_receipt_sha256",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(dict(value), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if path.is_symlink():
            digest.update(f"L\0{relative}\0{os.readlink(path)}\n".encode())
        elif path.is_file():
            digest.update(f"F\0{relative}\0{path.stat().st_size}\0".encode())
            digest.update(_sha256(path).encode()); digest.update(b"\n")
    return digest.hexdigest()


def _managed_codex() -> str | None:
    configured = os.environ.get("OPENROAD_PLATFORM_CODEX_EXECUTABLE")
    candidates = [Path(configured).expanduser()] if configured else []
    if discovered := shutil.which("codex"):
        candidates.append(Path(discovered))
    nvm = Path.home() / ".nvm/versions/node"
    if nvm.is_dir():
        candidates.extend(sorted(nvm.glob("*/bin/codex"), reverse=True))
    for candidate in candidates:
        lexical = candidate.absolute()
        if lexical.resolve().is_file() and os.access(lexical.resolve(), os.X_OK):
            return str(lexical)
    return None


def _validate_source(source: Path) -> dict[str, Any]:
    if not source.is_dir():
        raise FileNotFoundError(f"A2-ORFO source is missing: {source}")
    git = ("git", "-C", str(source))
    head = subprocess.check_output((*git, "rev-parse", "HEAD"), text=True).strip()
    tree = subprocess.check_output((*git, "rev-parse", "HEAD^{tree}"), text=True).strip()
    if head != A2_ORFO_UPSTREAM_COMMIT or tree != A2_ORFO_UPSTREAM_TREE:
        raise ValueError("A2-ORFO execution source does not match the admitted commit/tree")
    if subprocess.run((*git, "symbolic-ref", "-q", "HEAD"), stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL, check=False).returncode == 0:
        raise ValueError("A2-ORFO execution source must be detached")
    if subprocess.check_output((*git, "status", "--porcelain", "--untracked-files=all"), text=True):
        raise ValueError("A2-ORFO execution source must be clean")
    license_path = source / "LICENSE"
    if _sha256(license_path) != "243601633b171278cd98f9ea495cbfc74aad9d7fc062c6e7c81e20d1fc44a22f":
        raise ValueError("A2-ORFO BSD-3-Clause license hash changed")
    for relative, expected in _HASHES.items():
        if _sha256(source / relative) != expected:
            raise ValueError(f"A2-ORFO admitted source file changed: {relative}")
    return {"commit": head, "tree": tree, "license": "BSD-3-Clause"}


def _validate_model(model: Path) -> None:
    if not model.is_dir() or _tree_sha256(model) != A2_ORFO_MODEL_TREE_SHA256:
        raise ValueError("A2-ORFO embedding model does not match the admitted exact-commit tree")
    if _sha256(model / "LICENSE") != "4b0dfefcb74f1e50a8df72a9f2bf0088753f8568bc479387292469b4948705d4":
        raise ValueError("A2-ORFO embedding model Apache-2.0 license hash changed")


def _protocol(raw: Mapping[str, Any], *, design: str, platform_name: str) -> dict[str, Any]:
    if set(raw) != _PROTOCOL_KEYS or raw.get("design") != design or raw.get("platform") != platform_name:
        raise ValueError("A2-ORFO protocol has unknown/missing fields or identity drift")
    if raw.get("a2_orfo_commit") != A2_ORFO_UPSTREAM_COMMIT:
        raise ValueError("A2-ORFO protocol source commit drift")
    if list(raw.get("objective_set") or ()) != list(A2_ORFO_OBJECTIVES):
        raise ValueError("A2-ORFO protocol must preserve ECP, DWL, and COMBO")
    for name in ("protocol_id", "orfs_executor_commit", "seed_policy", "evaluator"):
        if not isinstance(raw.get(name), str) or not raw[name]:
            raise ValueError(f"A2-ORFO protocol {name} is invalid")
    for name in ("design_bundle_sha256", "pdk_bundle_sha256", "toolchain_receipt_sha256"):
        value = raw.get(name)
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError(f"A2-ORFO protocol {name} must be SHA-256")
    budget = raw.get("budget")
    if (not isinstance(budget, Mapping) or set(budget) != {"minimum_successful_observations", "feedback_steps"}
            or any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in budget.values())):
        raise ValueError("A2-ORFO protocol budget is invalid")
    baselines = raw.get("objective_baselines")
    if (not isinstance(baselines, Mapping) or set(baselines) != {"ecp", "dwl"}
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)) or v <= 0
                   for v in baselines.values())):
        raise ValueError("A2-ORFO frozen objective baselines are invalid")
    return json.loads(json.dumps(raw, sort_keys=True))


def _constraints(source: Path, *, platform_name: str) -> dict[str, dict[str, Any]]:
    raw = json.loads((source / "AutoTuner-integration/ORFS-with-AutoTuner/constraints.json").read_text())
    resolved = {}
    for name in A2_ORFO_PARAMETERS:
        item = raw[name]
        if item.get("pdk_specific") is True:
            item = item[platform_name]
        kind = item["type"]
        resolved[name] = ({"type": kind, "values": list(item["values"])} if kind == "binary"
                          else {"type": kind, "range": list(item["range"])})
    return resolved


@dataclass(frozen=True)
class A2ORFODomain:
    design: str
    platform: str
    constraints: dict[str, dict[str, Any]]
    upstream_constraints_sha256: str
    experiment_protocol: dict[str, Any]

    @classmethod
    def from_upstream(cls, *, source_root: str | Path, design: str, platform_name: str,
                      experiment_protocol: Mapping[str, Any]) -> "A2ORFODomain":
        if design not in {"aes", "ibex", "jpeg"} or platform_name not in {"asap7", "sky130hd"}:
            raise ValueError("A2-ORFO supports the admitted upstream 2D design/platform set")
        source = Path(source_root).expanduser().resolve()
        path = source / "AutoTuner-integration/ORFS-with-AutoTuner/constraints.json"
        return cls(design, platform_name, _constraints(source, platform_name=platform_name),
                   _sha256(path), _protocol(experiment_protocol, design=design,
                                            platform_name=platform_name))

    def to_dict(self) -> dict[str, Any]:
        protocol = _protocol(self.experiment_protocol, design=self.design, platform_name=self.platform)
        value = {
            "schema_version": 1, "kind": "a2-orfo-upstream-full-12d",
            "design": self.design, "platform": self.platform,
            "parameter_names": list(A2_ORFO_PARAMETERS), "constraints": self.constraints,
            "upstream_constraints_sha256": self.upstream_constraints_sha256,
            "experiment_protocol": protocol, "protocol_sha256": _digest(protocol),
            "variable_clock_semantics": True,
        }
        value["domain_sha256"] = _digest(value)
        return value

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "A2ORFODomain":
        if not isinstance(payload, Mapping):
            raise ValueError("A2-ORFO domain must be an object")
        expected = {
            "schema_version", "kind", "design", "platform", "parameter_names",
            "constraints", "upstream_constraints_sha256", "experiment_protocol",
            "protocol_sha256", "variable_clock_semantics", "domain_sha256",
        }
        if set(payload) != expected or payload.get("schema_version") != 1 or \
                payload.get("kind") != "a2-orfo-upstream-full-12d":
            raise ValueError("A2-ORFO domain envelope is malformed")
        unsigned = dict(payload); claimed_domain = unsigned.pop("domain_sha256")
        if claimed_domain != _digest(unsigned):
            raise ValueError("A2-ORFO domain hash is invalid")
        if (list(payload.get("parameter_names") or ()) != list(A2_ORFO_PARAMETERS)
                or payload.get("variable_clock_semantics") is not True):
            raise ValueError("A2-ORFO domain must preserve full 12-D variable-clock semantics")
        constraints = payload.get("constraints")
        if not isinstance(constraints, Mapping) or set(constraints) != set(A2_ORFO_PARAMETERS):
            raise ValueError("A2-ORFO domain constraints are incomplete")
        protocol = _protocol(
            payload["experiment_protocol"], design=str(payload["design"]),
            platform_name=str(payload["platform"]))
        if payload.get("protocol_sha256") != _digest(protocol):
            raise ValueError("A2-ORFO domain protocol hash is invalid")
        constraint_sha = payload.get("upstream_constraints_sha256")
        if not isinstance(constraint_sha, str) or len(constraint_sha) != 64 or any(
                char not in "0123456789abcdef" for char in constraint_sha):
            raise ValueError("A2-ORFO upstream constraint hash is invalid")
        result = cls(str(payload["design"]), str(payload["platform"]),
                     json.loads(json.dumps(constraints)), constraint_sha, protocol)
        # Validate the complete rule schema through representative endpoints.
        for name, rule in result.constraints.items():
            if not isinstance(rule, Mapping) or rule.get("type") not in {
                    "integer", "float", "binary"}:
                raise ValueError(f"A2-ORFO constraint {name} is malformed")
            if rule["type"] == "binary":
                if (set(rule) != {"type", "values"} or not isinstance(rule["values"], list)
                        or not rule["values"]):
                    raise ValueError(f"A2-ORFO binary constraint {name} is malformed")
            elif (set(rule) != {"type", "range"} or not isinstance(rule["range"], list)
                  or len(rule["range"]) != 2
                  or float(rule["range"][0]) > float(rule["range"][1])):
                raise ValueError(f"A2-ORFO range constraint {name} is malformed")
        return result

    def validate_candidate(self, candidate: Mapping[str, Any]) -> None:
        if set(candidate) != set(A2_ORFO_PARAMETERS):
            raise ValueError("A2-ORFO candidate must preserve all 12 upstream parameters")
        for name in A2_ORFO_PARAMETERS:
            value, rule = candidate[name], self.constraints[name]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError(f"A2-ORFO candidate {name} is not finite numeric data")
            if rule["type"] in {"integer", "binary"} and int(value) != value:
                raise ValueError(f"A2-ORFO candidate {name} must be integral")
            if rule["type"] == "binary" and int(value) not in rule["values"]:
                raise ValueError(f"A2-ORFO candidate {name} is outside the upstream values")
            if rule["type"] != "binary" and not float(rule["range"][0]) <= float(value) <= float(rule["range"][1]):
                raise ValueError(f"A2-ORFO candidate {name} is outside the upstream range")

    @property
    def protocol_sha256(self) -> str:
        return _digest(self.experiment_protocol)

    def validate_observation(self, observation: Mapping[str, Any]) -> None:
        if observation.get("protocol_sha256") != self.protocol_sha256:
            raise ValueError("A2-ORFO observation protocol does not match")
        candidate, metrics = observation.get("candidate"), observation.get("metrics")
        if not isinstance(candidate, Mapping) or not isinstance(metrics, Mapping):
            raise ValueError("A2-ORFO observation requires candidate and metrics")
        self.validate_candidate(candidate)
        refs = observation.get("artifact_refs")
        if not isinstance(refs, list) or not refs or not all(isinstance(v, str) and v for v in refs):
            raise ValueError("A2-ORFO observation requires source-evidence references")


def build_a2_orfo_policy_task(*, project_id: str, design_id: str, objective: str,
                              observations: Sequence[Mapping[str, Any]], domain: A2ORFODomain,
                              n_suggestions: int, optimizer_seed: int,
                              prior_checkpoint: Mapping[str, Any] | None = None,
                              task_id: str | None = None, timeout_seconds: int = 3600) -> TaskSpec:
    # The pinned native launcher uses PARALLEL_RUNS=25. Keep the same bounded
    # contract as the other external optimizers; 16 was an early smoke limit
    # that made the product protocol impossible to configure.
    if objective not in A2_ORFO_OBJECTIVES or not 1 <= n_suggestions <= 64:
        raise ValueError("A2-ORFO objective or suggestion count is invalid")
    if isinstance(optimizer_seed, bool) or not isinstance(optimizer_seed, int) or optimizer_seed < 0:
        raise ValueError("A2-ORFO optimizer seed must be non-negative")
    usable = 0
    for observation in observations:
        domain.validate_observation(observation)
        # A completed EDA run with measured objective data is valid optimizer
        # feedback even when the protected signoff gate marks it infeasible.
        # Dropping constraint-violating measurements would bias the search.
        usable += int(observation.get("status") == "succeeded" and bool(observation.get("metrics")))
    required = int(domain.experiment_protocol["budget"]["minimum_successful_observations"])
    if usable < required:
        raise ValueError(f"A2-ORFO native GPR requires at least {required} successful observations")
    checkpoint = None
    if prior_checkpoint is not None:
        if (not isinstance(prior_checkpoint, Mapping)
                or set(prior_checkpoint) != {"schema_version", "optimized_prompts", "sha256"}):
            raise ValueError("A2-ORFO prior checkpoint is malformed")
        unsigned = {"schema_version": prior_checkpoint["schema_version"],
                    "optimized_prompts": prior_checkpoint["optimized_prompts"]}
        if prior_checkpoint["sha256"] != _digest(unsigned):
            raise ValueError("A2-ORFO prior checkpoint hash is invalid")
        checkpoint = dict(prior_checkpoint)
    inputs = {"mode": "native_policy", "design": domain.design, "platform": domain.platform,
              "objective": objective, "observations": [dict(row) for row in observations],
              "parameter_domain": domain.to_dict(), "n_suggestions": n_suggestions,
              "optimizer_seed": optimizer_seed}
    if checkpoint is not None:
        inputs["prior_checkpoint"] = checkpoint
    task = TaskSpec(
        task_id=task_id or f"a2-orfo-policy-{uuid.uuid4().hex}", project_id=project_id,
        design_id=design_id, plugin_id=A2_ORFO_PLUGIN_ID,
        inputs=inputs,
        timeout_seconds=timeout_seconds, max_attempts=1,
        expected_artifacts=("optimizer_dataset", "optimizer_candidates", "optimizer_trace",
                            "optimizer_checkpoint", "knowledge_retrieval", "model_provider_trace",
                            "upstream_source_lock"),
        labels={"optimizer_origin": f"external:A2-ORFO@{A2_ORFO_UPSTREAM_COMMIT}",
                "execution_owner": "platform-runtime", "model_substitution": "DeepSeek-R1->gpt-5.6-terra",
                "variable_clock_semantics": "true"},
    )
    task.validate(); return task


def build_a2_orfo_initialization_task(
    *, project_id: str, design_id: str, objective: str, domain: A2ORFODomain,
    count: int, optimizer_seed: int, task_id: str | None = None,
    timeout_seconds: int = 3600,
) -> TaskSpec:
    """Invoke the pinned upstream ``generate_initial_parameters`` method."""
    if objective not in A2_ORFO_OBJECTIVES:
        raise ValueError("A2-ORFO objective is invalid")
    if (isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 64
            or isinstance(optimizer_seed, bool) or not isinstance(optimizer_seed, int)
            or optimizer_seed < 0):
        raise ValueError("A2-ORFO initialization count or seed is invalid")
    inputs = {
        "mode": "native_initialize", "design": domain.design,
        "platform": domain.platform, "objective": objective,
        "observations": [], "parameter_domain": domain.to_dict(),
        "n_suggestions": count, "optimizer_seed": optimizer_seed,
    }
    task = TaskSpec(
        task_id=task_id or f"a2-orfo-initialize-{uuid.uuid4().hex}",
        project_id=project_id, design_id=design_id, plugin_id=A2_ORFO_PLUGIN_ID,
        inputs=inputs, timeout_seconds=timeout_seconds, max_attempts=1,
        expected_artifacts=(
            "optimizer_dataset", "optimizer_candidates", "optimizer_trace",
            "optimizer_checkpoint", "knowledge_retrieval", "model_provider_trace",
            "upstream_source_lock"),
        labels={
            "optimizer_origin": f"external:A2-ORFO@{A2_ORFO_UPSTREAM_COMMIT}",
            "upstream_entrypoint": "OptimizationWorkflow.generate_initial_parameters",
            "execution_owner": "platform-runtime", "variable_clock_semantics": "true",
        },
    )
    task.validate()
    return task


def a2_orfo_plugin_manifest(source_root: str | Path, *, model_root: str | Path,
                            python_executable: str | Path = sys.executable,
                            codex_executable: str | Path | None = None,
                            default_timeout_seconds: int = 3600) -> PluginManifest:
    source, model = Path(source_root).expanduser().resolve(), Path(model_root).expanduser().resolve()
    python = Path(python_executable).expanduser().absolute()
    if not python.is_file():
        raise FileNotFoundError("A2-ORFO isolated Python is missing")
    _validate_source(source); _validate_model(model)
    codex = str(Path(codex_executable).expanduser().absolute()) if codex_executable else _managed_codex()
    if not codex or not Path(codex).resolve().is_file():
        raise FileNotFoundError("A2-ORFO requires a platform-managed Codex provider")
    root = Path(__file__).resolve().parents[4]
    adapter = root / "integrations/a2_orfo/a2_orfo_adapter.py"
    environment = {
        "A2_ORFO_SOURCE": str(source), "A2_ORFO_EXPECTED_COMMIT": A2_ORFO_UPSTREAM_COMMIT,
        "A2_ORFO_EXPECTED_TREE": A2_ORFO_UPSTREAM_TREE, "A2_ORFO_MODEL": str(model),
        "A2_ORFO_MODEL_TREE_SHA256": A2_ORFO_MODEL_TREE_SHA256,
        "A2_ORFO_CODEX_EXECUTABLE": codex, "PYTHONDONTWRITEBYTECODE": "1",
        "PATH": f"{Path(codex).parent}:{python.parent}:/usr/bin:/bin",
    }
    manifest = PluginManifest(
        plugin_id=A2_ORFO_PLUGIN_ID, plugin_version=A2_ORFO_PLUGIN_VERSION,
        adapter_entry=(str(python), str(adapter)),
        capabilities=("optimizer.l2.a2-orfo-initialize",
                      "optimizer.l2.a2-orfo-policy",
                      "optimizer.l2.a2-orfo-feedback"),
        supported_arch=(platform.machine(),),
        input_schema={"type": "object", "required": ["mode", "design", "platform", "objective",
                                                         "observations", "parameter_domain"]},
        output_schema={"type": "object", "required": ["status", "artifacts", "provenance"]},
        required_tools=("git", "python3", "codex"), default_timeout_seconds=default_timeout_seconds,
        artifact_rules=tuple({"kind": kind, "required": False} for kind in (
            "optimizer_dataset", "optimizer_candidates", "optimizer_trace", "optimizer_checkpoint",
            "knowledge_retrieval", "model_provider_trace", "upstream_source_lock",
            "runtime_protocol_receipt")),
        environment=environment,
    )
    manifest.validate(); return manifest
