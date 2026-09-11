#!/usr/bin/env python3
"""Attempt-isolated adapter for the pinned native A2-ORFO policy workflow."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import random
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


HERE = Path(__file__).resolve().parent
PARAMETER_MAP = {
    "core_util": "UTIL", "cell_pad_global": "GP_PAD", "cell_pad_detail": "DP_PAD",
    "synth_flatten": "HIER_SYNTH", "pin_layer": "PIN_ADJ", "above_layer": "UP_ADJ",
    "tns": "TNS_End_Percent", "lb_addon": "LB_ADDON", "cts_size": "CTS_CSIZE",
    "cts_diameter": "CTS_CDIA", "enable_dpo": "DPO", "clk_period": "CLK",
}
PARAMETERS = tuple(PARAMETER_MAP.values())
OBJECTIVES = {"ECP", "DWL", "COMBO"}
SOURCE_FILE_HASHES = {
    "optimize.py": "01d3ac68abf03880c6b9b2bf6e6db5484ab247314a2df0643f865c3565a14ad5",
    "constraint_optimizer.py": "0b891e70c4c80b390909795281a6a786e29ece9175dfe52c99d130b1d4d10ceb",
    "inspectfuncs.py": "39179bf246a2b0a9cd7d950ec9c52c5392fc8c1c38aa0434a001cf1c7dc00cfb",
    "modelfuncs.py": "342307d8efbf60bed755aa137dc9ec07c097da69ee81d549e3498d65bc7fc60d",
    "prompts.py": "7edc2d26739324128623b7dcb5e0e5a3956ab8ea191b5ddeff5263624a38e852",
    "AutoTuner-integration/ORFS-with-AutoTuner/constraints.json":
        "9de2da8058266f8287b153a06ecafbc3698281b24ea226f9e72e458336dcf7ad",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _write(path: Path, value: Any, *, sort_keys: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=sort_keys) + "\n", encoding="utf-8")


def _source() -> tuple[Path, dict[str, Any]]:
    source = Path(os.environ["A2_ORFO_SOURCE"]).expanduser().resolve()
    git = ("git", "-C", str(source))
    head = subprocess.check_output((*git, "rev-parse", "HEAD"), text=True).strip()
    tree = subprocess.check_output((*git, "rev-parse", "HEAD^{tree}"), text=True).strip()
    if head != os.environ["A2_ORFO_EXPECTED_COMMIT"] or tree != os.environ["A2_ORFO_EXPECTED_TREE"]:
        raise ValueError("A2-ORFO source commit/tree differs from the manifest admission")
    if subprocess.run((*git, "symbolic-ref", "-q", "HEAD"), stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL, check=False).returncode == 0:
        raise ValueError("A2-ORFO source must be detached")
    if subprocess.check_output((*git, "status", "--porcelain", "--untracked-files=all"), text=True):
        raise ValueError("A2-ORFO source must be clean")
    for relative, expected in SOURCE_FILE_HASHES.items():
        if _sha256(source / relative) != expected:
            raise ValueError(f"A2-ORFO source file changed: {relative}")
    license_hash = _sha256(source / "LICENSE")
    if license_hash != "243601633b171278cd98f9ea495cbfc74aad9d7fc062c6e7c81e20d1fc44a22f":
        raise ValueError("A2-ORFO source license changed")
    return source, {"repository": "https://github.com/CODA-Team/TaiWei-flow-Agent.git",
                    "commit": head, "tree": tree, "license": "BSD-3-Clause",
                    "license_sha256": license_hash, "algorithm_files": SOURCE_FILE_HASHES}


def _model() -> tuple[Path, dict[str, Any]]:
    model = Path(os.environ["A2_ORFO_MODEL"]).expanduser().resolve()
    tree = _tree_sha256(model)
    if tree != os.environ["A2_ORFO_MODEL_TREE_SHA256"]:
        raise ValueError("A2-ORFO embedding model tree changed")
    license_hash = _sha256(model / "LICENSE")
    if license_hash != "4b0dfefcb74f1e50a8df72a9f2bf0088753f8568bc479387292469b4948705d4":
        raise ValueError("A2-ORFO model license changed")
    return model, {"repository": "https://huggingface.co/mixedbread-ai/mxbai-embed-large-v1",
                   "commit": "b33106f585b9ce46904ad7443a3b52b7a63e231c",
                   "tree_sha256": tree, "license": "Apache-2.0", "license_sha256": license_hash}


def _private_archive(source: Path, destination: Path) -> None:
    archive = destination.parent / "upstream-source.tar"
    with archive.open("wb") as stream:
        completed = subprocess.run(("git", "-C", str(source), "archive", "--format=tar", "HEAD"),
                                   stdout=stream, stderr=subprocess.PIPE, check=False)
    if completed.returncode:
        raise RuntimeError(completed.stderr.decode(errors="replace"))
    destination.mkdir(parents=True)
    with tarfile.open(archive, "r:") as bundle:
        for member in bundle.getmembers():
            target = (destination / member.name).resolve()
            try:
                target.relative_to(destination.resolve())
            except ValueError as exc:
                raise ValueError("unsafe member in A2-ORFO git archive") from exc
            if member.issym() or member.islnk():
                raise ValueError("A2-ORFO source archive unexpectedly contains a link")
        bundle.extractall(destination, filter="data")
    archive.unlink()


def _runtime_protocol(workspace: Path) -> Mapping[str, Any]:
    configured = os.environ.get("A2_ORFO_PROTOCOL_RECEIPT")
    expected = os.environ.get("A2_ORFO_PROTOCOL_RECEIPT_SHA256")
    if not configured or not expected:
        raise ValueError("Runtime did not inject the A2-ORFO protocol receipt")
    path = Path(configured).resolve()
    try:
        path.relative_to(workspace.resolve())
    except ValueError as exc:
        raise ValueError("A2-ORFO Runtime protocol receipt is outside the attempt") from exc
    if _sha256(path) != expected:
        raise ValueError("A2-ORFO Runtime protocol receipt digest differs")
    envelope = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(envelope, Mapping) or envelope.get("schema_version") != 1
            or not isinstance(envelope.get("protocol"), Mapping)):
        raise ValueError("A2-ORFO Runtime protocol receipt is malformed")
    return envelope["protocol"]


def _validate_domain(domain: Mapping[str, Any], *, design: str, platform: str,
                     source: Path, observations: list[Mapping[str, Any]]) -> None:
    keys = {"schema_version", "kind", "design", "platform", "parameter_names", "constraints",
            "upstream_constraints_sha256", "experiment_protocol", "protocol_sha256",
            "variable_clock_semantics", "domain_sha256"}
    if (set(domain) != keys or domain.get("schema_version") != 1
            or domain.get("kind") != "a2-orfo-upstream-full-12d"
            or domain.get("design") != design or domain.get("platform") != platform
            or domain.get("parameter_names") != list(PARAMETERS)
            or domain.get("variable_clock_semantics") is not True):
        raise ValueError("A2-ORFO policy domain is missing, reduced, reordered, or drifted")
    if domain.get("domain_sha256") != _digest({k: v for k, v in domain.items() if k != "domain_sha256"}):
        raise ValueError("A2-ORFO domain hash is invalid")
    protocol = domain.get("experiment_protocol")
    if not isinstance(protocol, Mapping) or domain.get("protocol_sha256") != _digest(protocol):
        raise ValueError("A2-ORFO protocol hash is invalid")
    if protocol.get("a2_orfo_commit") != os.environ["A2_ORFO_EXPECTED_COMMIT"]:
        raise ValueError("A2-ORFO protocol is bound to another policy source")
    constraints_path = source / "AutoTuner-integration/ORFS-with-AutoTuner/constraints.json"
    if domain.get("upstream_constraints_sha256") != _sha256(constraints_path):
        raise ValueError("A2-ORFO domain is not bound to upstream constraints")
    constraints = domain.get("constraints")
    if not isinstance(constraints, Mapping) or set(constraints) != set(PARAMETERS):
        raise ValueError("A2-ORFO constraints do not preserve all 12 dimensions")
    for row in observations:
        if row.get("protocol_sha256") != domain["protocol_sha256"]:
            raise ValueError("A2-ORFO observation protocol drift")
        _candidate(row.get("candidate"), constraints)
        refs = row.get("artifact_refs")
        if not isinstance(refs, list) or not refs:
            raise ValueError("A2-ORFO observations must cite Runtime artifacts")


def _candidate(value: Any, constraints: Mapping[str, Any]) -> dict[str, int | float]:
    if not isinstance(value, Mapping) or set(value) != set(PARAMETERS):
        raise ValueError("candidate is not a complete A2-ORFO 12-D point")
    result = {}
    for name in PARAMETERS:
        raw, rule = value[name], constraints[name]
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(float(raw)):
            raise ValueError(f"candidate {name} is not numeric")
        if rule["type"] in {"integer", "binary"}:
            if int(raw) != raw:
                raise ValueError(f"candidate {name} is not integral")
            normalized: int | float = int(raw)
        else:
            normalized = float(raw)
        if rule["type"] == "binary":
            valid = normalized in rule["values"]
        else:
            valid = float(rule["range"][0]) <= float(normalized) <= float(rule["range"][1])
        if not valid:
            raise ValueError(f"candidate {name} is outside the A2-ORFO domain")
        result[name] = normalized
    return result


def _metric(metrics: Mapping[str, Any], *names: str, default: float = 0.0) -> float:
    for name in names:
        value = metrics.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
            return float(value)
    return default


def _materialize_observations(root: Path, *, design: str, platform: str,
                              observations: list[Mapping[str, Any]]) -> None:
    design_dir = root / "designs" / platform / design
    logs_dir = root / "logs"
    design_dir.mkdir(parents=True); logs_dir.mkdir()
    with (design_dir / f"{platform}_{design}.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream); writer.writerow(PARAMETER_MAP)
        for row in observations:
            candidate = row["candidate"]
            writer.writerow([candidate[published] for published in PARAMETER_MAP.values()])
    initial = observations[0]["candidate"]
    (design_dir / "config.mk").write_text("\n".join(
        f"export {local}={initial[published]}" for local, published in PARAMETER_MAP.items()) + "\n",
        encoding="utf-8")
    (design_dir / "constraint.sdc").write_text(
        f"set clk_period {initial['CLK']}\n# Adapter context only; protected SDC identified by protocol hash.\n",
        encoding="utf-8")
    for index, row in enumerate(observations, 1):
        candidate, metrics = row["candidate"], row.get("metrics") or {}
        status = row.get("status")
        log = logs_dir / f"{platform}_{design}_run{index}.log"
        if status == "succeeded" and metrics:
            slack = _metric(metrics, "finish__timing__setup__ws", "setup_wns_ns")
            tns = _metric(metrics, "finish__timing__setup__tns", "setup_tns_ns")
            ecp = _metric(metrics, "ECP_final", default=float(candidate["CLK"]) - slack)
            wire = _metric(metrics, "detailedroute__route__wirelength", "wirelength_um", default=1.0)
            cts_wire = _metric(metrics, "cts__route__wirelength", default=wire * .9)
            drc = int(_metric(metrics, "detailedroute__route__drc_errors", "drc_errors"))
            text = (
                f"clock period to {candidate['CLK']}\n"
                "Report metrics stage 4, cts final\n"
                f"wns max {slack}\nTotal wirelength: {cts_wire}\n"
                "Report metrics stage 6, finish...\n"
                f"wns max {slack}\ntns max {tns}\nclock period_min = {ecp}\n"
                f"[INFO DRT-0198] Complete detail routing. Total wire length = {wire}\n"
                f"[INFO DRT-0199] Number of violations = {drc}\n"
                "finish report_design_area\n6_report\n"
            )
        else:
            failure = str(row.get("failure_message") or row.get("failure_category") or "measured candidate failed")
            text = f"clock period to {candidate['CLK']}\nERROR: {failure}\n"
        log.write_text(text, encoding="utf-8")


def _materialize_initial_context(root: Path, *, design: str, platform: str,
                                 constraints: Mapping[str, Any]) -> None:
    """Create only constructor context; upstream generates every candidate."""
    design_dir = root / "designs" / platform / design
    design_dir.mkdir(parents=True)
    (root / "logs").mkdir(exist_ok=True)
    initial = {}
    for local, published in PARAMETER_MAP.items():
        rule = constraints[published]
        values = rule["values"] if rule["type"] == "binary" else rule["range"]
        value = values[0] if rule["type"] in {"integer", "binary"} else \
            (float(values[0]) + float(values[-1])) / 2
        initial[local] = value
    (design_dir / "config.mk").write_text("\n".join(
        f"export {name}={value}" for name, value in initial.items()) + "\n",
        encoding="utf-8")
    (design_dir / "constraint.sdc").write_text(
        f"set clk_period {initial['clk_period']}\n"
        "# Attempt-private constructor context; protected SDC is protocol-bound.\n",
        encoding="utf-8")


def _patch_baselines(root: Path, *, design: str, platform: str, protocol: Mapping[str, Any]) -> dict[str, Any]:
    path = root / "opt_config.json"
    original = path.read_bytes(); config = json.loads(original)
    matches = 0
    for item in config.get("configurations", []):
        if item.get("design") == design and item.get("platform") == platform and item.get("goal") in OBJECTIVES:
            item["baseline"] = {**dict(item.get("baseline") or {}),
                                "ecp_base": protocol["objective_baselines"]["ecp"],
                                "wl_base": protocol["objective_baselines"]["dwl"]}
            matches += 1
    if matches != 3:
        raise ValueError("A2-ORFO private baseline projection did not find all objective configs")
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"path": "opt_config.json", "before_sha256": hashlib.sha256(original).hexdigest(),
            "after_sha256": _sha256(path), "scope": "attempt-private copy only",
            "reason": "native launcher normally injects measured baselines; adapter uses frozen protocol values"}


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import pinned A2-ORFO module {path}")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


def _result(*, status: str, code: int, started: str, artifacts=(), provenance=None,
            failure=None) -> dict[str, Any]:
    return {"schema_version": 1, "status": status, "exit_code": code,
            "started_at": started, "ended_at": _now(), "metrics": [],
            "artifacts": list(artifacts), "failure": failure,
            "provenance": dict(provenance or {})}


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True); args = parser.parse_args(); started = _now()
    try:
        request = json.loads(args.request.read_text(encoding="utf-8")); task = request["task"]
        inputs = task.get("inputs")
        if (request.get("plugin", {}).get("plugin_id") != "a2-orfo"
                or task.get("plugin_id") != "a2-orfo" or not isinstance(inputs, Mapping)
                or inputs.get("mode") not in {"native_initialize", "native_policy"}):
            raise ValueError("request is not an admitted A2-ORFO native task")
        mode = str(inputs["mode"])
        design, platform, objective = (str(inputs.get(key, "")) for key in ("design", "platform", "objective"))
        if design not in {"aes", "ibex", "jpeg"} or platform not in {"asap7", "sky130hd"} or objective not in OBJECTIVES:
            raise ValueError("unsupported A2-ORFO design/platform/objective")
        observations = inputs.get("observations")
        domain = inputs.get("parameter_domain")
        if not isinstance(observations, list) or not all(isinstance(row, Mapping) for row in observations):
            raise ValueError("A2-ORFO observations must be objects")
        if not isinstance(domain, Mapping):
            raise ValueError("A2-ORFO typed domain is missing")
        source, source_receipt = _source(); model, model_receipt = _model()
        if dict(_runtime_protocol(args.result.parent)) != dict(domain.get("experiment_protocol") or {}):
            raise ValueError("A2-ORFO request protocol differs from Runtime authority")
        _validate_domain(domain, design=design, platform=platform, source=source,
                         observations=observations)
        minimum = int(domain["experiment_protocol"]["budget"]["minimum_successful_observations"])
        successes = sum(row.get("status") == "succeeded" and bool(row.get("metrics")) for row in observations)
        if mode == "native_policy" and successes < minimum:
            raise ValueError(f"native A2-ORFO GPR requires at least {minimum} successful observations")
        if mode == "native_initialize" and observations:
            raise ValueError("A2-ORFO native initializer does not accept observations")
        root = args.result.parent.resolve(); private = root / "a2_upstream_private"
        _private_archive(source, private)
        models = private / "models"; models.mkdir(); (models / "mxbai-embed-large-v1").symlink_to(model)
        if mode == "native_policy":
            _materialize_observations(
                private, design=design, platform=platform, observations=observations)
        else:
            _materialize_initial_context(
                private, design=design, platform=platform,
                constraints=domain["constraints"])
        patch_receipt = _patch_baselines(private, design=design, platform=platform,
                                         protocol=domain["experiment_protocol"])
        prior = inputs.get("prior_checkpoint")
        if prior is not None:
            if not isinstance(prior, Mapping) or set(prior) != {"schema_version", "optimized_prompts", "sha256"}:
                raise ValueError("A2-ORFO prior checkpoint is malformed")
            canonical = {"schema_version": prior["schema_version"], "optimized_prompts": prior["optimized_prompts"]}
            if prior["sha256"] != _digest(canonical):
                raise ValueError("A2-ORFO prior checkpoint hash is invalid")
            prompt_path = private / "prompts_storage" / f"optimized_prompts_{design}-{platform}.json"
            _write(prompt_path, prior["optimized_prompts"])
        provider_module = _load(HERE / "a2_orfo_managed_provider.py", "a2_orfo_managed_provider")
        provider_trace = root / "model_provider_trace.json"
        provider = provider_module.ManagedCodexProvider(
            executable=os.environ["A2_ORFO_CODEX_EXECUTABLE"], trace_path=provider_trace)
        provider_module.install_openai_shim(provider)
        previous = Path.cwd(); old_key = os.environ.get("OPENAI_API_KEY")
        os.environ["OPENAI_API_KEY"] = "platform-managed-provider-sentinel"
        random.seed(int(inputs["optimizer_seed"]))
        try:
            os.chdir(private); sys.path.insert(0, str(private))
            upstream = _load(private / "optimize.py", "a2_orfo_pinned_optimize")
            retrievals: list[dict[str, Any]] = []
            native_rag = upstream.answerWithRAG
            def observed_rag(question, *rag_args, **rag_kwargs):
                content = native_rag(question, *rag_args, **rag_kwargs)
                retrievals.append({"query": question, "query_sha256": hashlib.sha256(question.encode()).hexdigest(),
                                   "content": content, "content_sha256": hashlib.sha256(str(content).encode()).hexdigest()})
                return content
            upstream.answerWithRAG = observed_rag
            workflow = upstream.OptimizationWorkflow(platform, design, objective)
            # ``optimize.py`` carries an older, divergent hard-coded range
            # table.  The same pinned repository publishes the native
            # AutoTuner contract in constraints.json.  Bind the workflow's
            # existing generator/GPR to that authoritative complete 12-D
            # contract before any analysis or proposal; never post-process a
            # generated point into range.
            workflow.parameter_names = list(PARAMETER_MAP)
            workflow.param_constraints = {}
            for local, published in PARAMETER_MAP.items():
                rule = domain["constraints"][published]
                workflow.param_constraints[local] = (
                    {"type": "int", "range": list(rule["values"])}
                    if rule["type"] == "binary"
                    else {"type": "int" if rule["type"] == "integer" else "float",
                          "range": list(rule["range"])}
                )
            domain_binding = {
                "source": "AutoTuner-integration/ORFS-with-AutoTuner/constraints.json",
                "source_sha256": domain["upstream_constraints_sha256"],
                "parameter_map": PARAMETER_MAP,
                "reason": "pinned optimize.py hard-coded ranges diverge from the same commit's published AutoTuner contract",
                "policy": "bind before native run_iteration; no candidate post-processing or dimension freezing",
            }
            import numpy as np
            np.random.seed(int(inputs["optimizer_seed"]))
            if mode == "native_initialize":
                workflow.generate_initial_parameters(int(inputs["n_suggestions"]))
            else:
                workflow.run_iteration(int(inputs["n_suggestions"]))
        finally:
            os.chdir(previous)
            if str(private) in sys.path: sys.path.remove(str(private))
            if old_key is None: os.environ.pop("OPENAI_API_KEY", None)
            else: os.environ["OPENAI_API_KEY"] = old_key
        csv_path = private / "designs" / platform / design / f"{platform}_{design}.csv"
        with csv_path.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        candidates = []
        for row in rows:
            raw = {PARAMETER_MAP[local]: float(value) for local, value in row.items()}
            for name in PARAMETERS:
                if domain["constraints"][name]["type"] in {"integer", "binary"}:
                    raw[name] = int(raw[name])
            candidates.append(_candidate(raw, domain["constraints"]))
        if len(candidates) != int(inputs["n_suggestions"]):
            raise RuntimeError("native A2-ORFO did not emit the requested number of candidates")
        prompt_file = private / "prompts_storage" / f"optimized_prompts_{design}-{platform}.json"
        optimized_prompts = json.loads(prompt_file.read_text()) if prompt_file.is_file() else {}
        checkpoint_unsigned = {"schema_version": 1, "optimized_prompts": optimized_prompts}
        checkpoint = {**checkpoint_unsigned, "sha256": _digest(checkpoint_unsigned)}
        dataset = root / "a2_observations.json"; candidate_path = root / "a2_candidates.json"
        trace = root / "a2_policy_trace.json"; checkpoint_path = root / "a2_checkpoint.json"
        retrieval_path = root / "a2_knowledge_retrieval.json"; lock_path = root / "a2_source_lock.json"
        if not provider_trace.is_file():
            _write(provider_trace, {"schema_version": 1, "calls": [],
                                    "reason": "native initializer uses no model call"})
        _write(dataset, observations); _write(candidate_path, candidates, sort_keys=False)
        _write(retrieval_path, {"schema_version": 1, "retrievals": retrievals,
                                "corpus_documents": len(getattr(workflow, "rag_docs", [])),
                                "embedding_dimension": int(workflow.rag_embeddings.shape[1])})
        _write(checkpoint_path, checkpoint)
        _write(lock_path, {"source": source_receipt, "model": model_receipt})
        _write(trace, {"schema_version": 1, "algorithm_owner": "upstream A2-ORFO",
                       "entrypoint": ("OptimizationWorkflow.generate_initial_parameters"
                                      if mode == "native_initialize" else
                                      "OptimizationWorkflow.run_iteration"),
                       "source_commit": source_receipt["commit"], "objective": objective,
                       "optimizer_seed": inputs["optimizer_seed"], "parameter_order": list(PARAMETERS),
                       "candidate_count": len(candidates), "observation_count": len(observations),
                       "successful_observation_count": successes, "private_context_patch": patch_receipt,
                       "upstream_domain_binding": domain_binding,
                       "denied_native_launchers": ["maindriver.sh", "run_parallel.sh", "run_or_job.py"],
                       "execution_boundary": "policy only; Runtime owns candidate EDA and protected QoR"})
        artifacts = [
            {"kind": "optimizer_dataset", "path": dataset.name},
            {"kind": "optimizer_candidates", "path": candidate_path.name},
            {"kind": "optimizer_trace", "path": trace.name},
            {"kind": "optimizer_checkpoint", "path": checkpoint_path.name},
            {"kind": "knowledge_retrieval", "path": retrieval_path.name},
            {"kind": "model_provider_trace", "path": provider_trace.name},
            {"kind": "upstream_source_lock", "path": lock_path.name},
        ]
        args.result.write_text(json.dumps(_result(
            status="succeeded", code=0, started=started, artifacts=artifacts,
            provenance={"adapter": ("a2-orfo-native-initializer"
                                     if mode == "native_initialize" else
                                     "a2-orfo-native-policy"),
                        "source_commit": source_receipt["commit"],
                        "requested_model": "DeepSeek-R1", "executed_model": "gpt-5.6-terra",
                        "candidate_domain": list(PARAMETERS), "runtime_owns_qor": True}), indent=2) + "\n")
        return 0
    except Exception as exc:
        args.result.parent.mkdir(parents=True, exist_ok=True)
        args.result.write_text(json.dumps(_result(
            status="failed", code=2, started=started,
            provenance={"adapter": "a2-orfo-native-policy"},
            failure={"category": "adapter_error", "message": str(exc)}), indent=2) + "\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
