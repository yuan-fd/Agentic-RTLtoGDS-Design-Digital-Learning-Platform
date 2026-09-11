from types import SimpleNamespace

import pytest

from apps.api.app import ApiState
from openroad_platform_contracts import TaskSpec


def _state():
    state = object.__new__(ApiState)
    source = SimpleNamespace(run_id="source-1", task_spec=TaskSpec(
        "task-1", "project", "design", plugin_id="l1-runtime-smoke",
        parameters={"place_density": 0.45}, labels={"owner_id": "u1"}))
    submitted = []
    state.runtime_store = SimpleNamespace(get_run=lambda run_id: source if run_id == "source-1" else submitted[0])
    state.runtime = SimpleNamespace(submit=lambda task, capability: submitted.append(SimpleNamespace(run_id="copy-1", task_spec=task)) or submitted[0])
    state.get_runtime_run = lambda run_id, **_: {"run": {"run_id": run_id}}
    state._submitted = submitted
    return state


def test_open_lab_copy_is_independent_and_bounded():
    state = _state()
    result = state.copy_teaching_run("source-1", parameters={"place_density": 0.6}, owner_id="u1")
    copied = state._submitted[0].task_spec
    assert result["source_run_id"] == "source-1"
    assert copied.task_id != "task-1"
    assert copied.parameters["place_density"] == 0.6
    assert copied.labels["teaching_source_run_id"] == "source-1"
    with pytest.raises(ValueError, match="unsupported"):
        state.copy_teaching_run("source-1", parameters={"shell": "rm -rf"}, owner_id="u1")
