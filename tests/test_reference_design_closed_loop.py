from pathlib import Path

from apps.api.app import ApiState


def test_reference_design_enters_same_closed_loop_as_uploaded_rtl(tmp_path, monkeypatch):
    orfs = tmp_path / "orfs"
    src = orfs / "flow/designs/src/aes"
    cfg = orfs / "flow/designs/asap7/aes"
    src.mkdir(parents=True); cfg.mkdir(parents=True)
    (src / "aes_cipher_top.v").write_text(
        "module aes_cipher_top(input clk, output y); assign y=clk; endmodule\n")
    (cfg / "constraint.sdc").write_text("create_clock -period 380 [get_ports clk]\n")
    state = ApiState(
        tmp_path / "platform.db", tmp_path / "uploads", orfs,
        design_root=tmp_path / "designs", legacy_root=tmp_path / "legacy",
        runtime_db_path=tmp_path / "runtime.db",
        optimization_db_path=tmp_path / "optimization.db",
        load_taiwei_plugin=False,
    )
    created = state.start_bayesian_closed_loop({
        "reference_design": "aes", "platform": "asap7",
        "experiment_key": "reference-aes", "max_rounds": 1,
        "repetitions": 2, "replica_or_seeds": [101, 211],
        "optimizer_backend": "sobol-scrambled-mixed-v1",
    })
    task = state.runtime_store.get_run(created["state"]["active_run_ids"][0]).task_spec
    assert task.design_id.startswith("orfs-ref-asap7-aes-")
    assert task.inputs["rtl_bundle"]["files"][0]["relative_path"] == "aes_cipher_top.v"
    assert task.inputs["sdc"]["sha256"]
    assert task.parameters["clock_period_ns"] == .380
    assert task.labels["design_bundle_sha256"]
