from __future__ import annotations

import importlib.util
from pathlib import Path


def _module():
    path = Path(__file__).parents[1] / "scripts" / "teaching_platform_doctor.py"
    spec = importlib.util.spec_from_file_location("teaching_platform_doctor", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_doctor_reports_server_environment_without_mutating_it(monkeypatch):
    module = _module()
    monkeypatch.setenv("ORFS_ROOT", str(Path(__file__).parents[2] / "OpenROAD-flow-scripts"))
    monkeypatch.setenv("OPENROAD_BIN", str(Path.home() / "bin/openroad"))
    monkeypatch.setenv("YOSYS_BIN", str(Path.home() / "bin/yosys"))
    report = module.doctor()
    assert report["schema_version"] == 1
    assert report["orfs_makefile"] is True
    assert report["modules"]["optuna"] is True
    assert report["tools"]["openroad"]["available"] is True
