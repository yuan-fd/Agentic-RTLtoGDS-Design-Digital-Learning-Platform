from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

import apps.api.app as api_app
from apps.api.app import ApiState


class _Runtime:
    def __init__(self, workspace: Path, sha256: str) -> None:
        self.workspace = workspace
        self.sha256 = sha256

    def describe(self, run_id: str) -> dict:
        if run_id == "sim-run":
            return {"stages": [{"attempts": [{
                "status": "succeeded", "workspace": str(self.workspace),
                "artifacts": [{"artifact_id": "simulation-report", "kind": "simulation_report",
                               "sha256": self.simulation_sha256,
                               "store_key": "outputs/simulation.json"}],
            }]}]}
        if run_id == "formal-run":
            return {"stages": [{"attempts": [{
                "status": "succeeded", "workspace": str(self.workspace),
                "artifacts": [{"artifact_id": "formal-report", "kind": "formal_report",
                               "sha256": self.formal_sha256,
                               "store_key": "outputs/formal.json"}],
            }]}]}
        assert run_id == "verify-run"
        return {"stages": [{"attempts": [{
            "status": "succeeded", "workspace": str(self.workspace),
            "artifacts": [{"kind": "rtl", "sha256": self.sha256,
                           "store_key": "outputs/candidate.sv"}],
        }]}]}


class _RuntimeStore:
    def __init__(self) -> None:
        self.records: dict[str, object] = {}

    def get_run(self, run_id: str) -> object:
        return self.records[run_id]


def _run(plugin_id: str, candidate_id: str, spec_id: str, *, status: str = "succeeded") -> object:
    return SimpleNamespace(
        status=status,
        task_spec=SimpleNamespace(plugin_id=plugin_id,
                                  labels={"candidate_id": candidate_id, "spec_id": spec_id}),
    )


def _state(tmp_path: Path) -> tuple[ApiState, dict]:
    source = b"module top(input a, output y); assign y = a; endmodule\n"
    digest = hashlib.sha256(source).hexdigest()
    state = object.__new__(ApiState)
    state.rtl_candidate_root = tmp_path / "candidates"
    state.rtl_candidate_root.mkdir()
    (state.rtl_candidate_root / f"{digest}.sv").write_bytes(source)
    workspace = tmp_path / "verify-workspace"; (workspace / "outputs").mkdir(parents=True)
    (workspace / "outputs/candidate.sv").write_bytes(source)
    simulation = b'{"pass": true}\n'
    (workspace / "outputs/simulation.json").write_bytes(simulation)
    formal = b'{"proved": true}\n'
    (workspace / "outputs/formal.json").write_bytes(formal)
    state.runtime = _Runtime(workspace, digest)
    state.runtime.simulation_sha256 = hashlib.sha256(simulation).hexdigest()
    state.runtime.formal_sha256 = hashlib.sha256(formal).hexdigest()
    state.runtime_store = _RuntimeStore()
    state.runtime_store.records = {
        "verify-run": _run("rtl-verify", "candidate-1", "spec-1"),
        "sim-run": _run("rtl-sim", "candidate-1", "spec-1"),
        "formal-run": _run("rtl-formal", "candidate-1", "spec-1"),
    }
    lineage = {
        "spec": {"design_id": "design-1", "top": "top", "clock": "clk",
                 "constraints": {"platform": "nangate45", "clock_period_ns": 7.5}},
        "candidates": [{
            "candidate_id": "candidate-1", "verification_id": "verify-1",
            "generator": "rtlscout-v2", "rtl_artifact_ref": f"artifact:rtl-candidate:{digest}",
        }],
        "checks": [
            {"candidate_id": "candidate-1", "check_kind": "compile_lint", "status": "passed",
             "detail": {"run_id": "verify-run"}},
            {"candidate_id": "candidate-1", "check_kind": "simulation", "status": "passed",
             "evidence_ref": "artifact:runtime:sim-run:simulation-report",
             "evidence_sha256": state.runtime.simulation_sha256,
             "detail": {"run_id": "sim-run"}},
        ],
    }
    state.get_rtl_lineage = lambda *args, **kwargs: lineage
    return state, lineage


def test_product_l2_resolves_only_runtime_backed_rtlscout_evidence(tmp_path):
    state, _ = _state(tmp_path)
    resolved = state._resolve_verified_rtl_for_l2(
        "spec-1", candidate_id="candidate-1", owner_id="owner", include_legacy=False,
    )
    assert resolved["design_id"] == "design-1"
    assert resolved["verification_run_id"] == "verify-run"
    assert resolved["rtl_path"].is_file()
    assert resolved["constraints"]["clock_period_ns"] == 7.5


def test_product_l2_accepts_runtime_backed_formal_evidence(tmp_path):
    state, lineage = _state(tmp_path)
    lineage["checks"][1] = {
        "candidate_id": "candidate-1", "check_kind": "formal", "status": "passed",
        "evidence_ref": "artifact:runtime:formal-run:formal-report",
        "evidence_sha256": state.runtime.formal_sha256,
        "detail": {"run_id": "formal-run"},
    }
    assert state._resolve_verified_rtl_for_l2("spec-1", candidate_id="candidate-1",
                                              owner_id="owner", include_legacy=False)["rtl_path"].is_file()


def test_product_l2_rejects_non_rtlscout_or_missing_functional_evidence(tmp_path):
    state, lineage = _state(tmp_path)
    lineage["candidates"][0]["generator"] = "uploaded-rtl"
    with pytest.raises(ValueError, match="RTLScout-v2"):
        state._resolve_verified_rtl_for_l2("spec-1", candidate_id=None,
                                           owner_id=None, include_legacy=False)
    lineage["candidates"][0]["generator"] = "rtlscout-v2"
    lineage["checks"] = lineage["checks"][:1]
    with pytest.raises(ValueError, match="functional verification"):
        state._resolve_verified_rtl_for_l2("spec-1", candidate_id=None,
                                           owner_id=None, include_legacy=False)


@pytest.mark.parametrize("mutation", [
    "missing_run", "wrong_plugin", "failed_run", "path_escape", "hash_mismatch",
    "forged_functional", "wrong_candidate_label", "wrong_spec_label",
    "functional_artifact_id_mismatch", "functional_report_sha_mismatch",
    "valid_plus_forged_functional", "compile_wrong_candidate_label", "compile_wrong_spec_label",
])
def test_product_l2_fails_closed_for_forged_or_invalid_runtime_evidence(tmp_path, mutation):
    state, lineage = _state(tmp_path)
    if mutation == "missing_run":
        lineage["checks"][0]["detail"] = {}
    elif mutation == "wrong_plugin":
        state.runtime_store.records["verify-run"] = _run("rtl-sim", "candidate-1", "spec-1")
    elif mutation == "failed_run":
        state.runtime_store.records["verify-run"] = _run("rtl-verify", "candidate-1", "spec-1", status="failed")
    elif mutation == "path_escape":
        outside = tmp_path / "outside.sv"; outside.write_text("module outside; endmodule\n")
        state.runtime.describe = lambda _run_id: {"stages": [{"attempts": [{
            "status": "succeeded", "workspace": str(state.runtime.workspace),
            "artifacts": [{"kind": "rtl", "sha256": state.runtime.sha256,
                           "store_key": "../../outside.sv"}],
        }]}]}
    elif mutation == "hash_mismatch":
        (state.runtime.workspace / "outputs/candidate.sv").write_text("module changed; endmodule\n")
    elif mutation == "forged_functional":
        state.runtime_store.records["sim-run"] = _run("rtl-verify", "candidate-1", "spec-1")
    elif mutation == "wrong_candidate_label":
        state.runtime_store.records["sim-run"] = _run("rtl-sim", "another-candidate", "spec-1")
    elif mutation == "wrong_spec_label":
        state.runtime_store.records["sim-run"] = _run("rtl-sim", "candidate-1", "another-spec")
    elif mutation == "compile_wrong_candidate_label":
        state.runtime_store.records["verify-run"] = _run("rtl-verify", "another-candidate", "spec-1")
    elif mutation == "compile_wrong_spec_label":
        state.runtime_store.records["verify-run"] = _run("rtl-verify", "candidate-1", "another-spec")
    elif mutation == "functional_artifact_id_mismatch":
        lineage["checks"][1]["evidence_ref"] = "artifact:runtime:sim-run:not-the-report"
    elif mutation == "functional_report_sha_mismatch":
        lineage["checks"][1]["evidence_sha256"] = "0" * 64
    elif mutation == "valid_plus_forged_functional":
        lineage["checks"].append({
            "candidate_id": "candidate-1", "check_kind": "simulation", "status": "passed",
            "evidence_ref": "artifact:runtime:sim-run:forged-report",
            "evidence_sha256": state.runtime.simulation_sha256,
            "detail": {"run_id": "sim-run"},
        })
    with pytest.raises(ValueError):
        state._resolve_verified_rtl_for_l2("spec-1", candidate_id="candidate-1",
                                           owner_id="owner", include_legacy=False)


def test_legacy_l2_loop_writes_fail_before_resolution_or_runtime(tmp_path, monkeypatch):
    state, _ = _state(tmp_path)
    captured = {}
    state._resolve_verified_rtl_for_l2 = lambda *_args, **_kwargs: captured.update(
        resolved=True)
    state._external_l2_service = lambda: SimpleNamespace(create=lambda **kwargs: (
        captured.update(checkpoint=kwargs) or {"pipeline_id": "loop-1"}))
    with pytest.raises(ValueError, match="complete 12-D variable-clock"):
        state.start_external_optimizer_loop(
            {"spec_id": "spec-1", "candidate_id": "candidate-1"},
            owner_id="owner",
        )
    with pytest.raises(ValueError, match="historical checkpoints are read-only"):
        state.advance_external_optimizer_loop("loop-1", owner_id="owner")
    assert captured == {}
