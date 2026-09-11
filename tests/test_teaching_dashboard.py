from apps.api.app import ApiState


def test_teaching_dashboard_is_a_compact_runtime_projection():
    state = object.__new__(ApiState)
    state.list_runtime_runs = lambda **kwargs: {"runs": [
        {"run_id": "queued-1", "status": "queued"},
        {"run_id": "done-1", "status": "succeeded"},
        {"run_id": "bad-1", "status": "failed"},
    ]}
    class Runtime:
        @staticmethod
        def get_run(run_id):
            class Run:
                task_spec = type("Task", (), {"labels": {"experiment_id": "exp-1", "teaching_mode": "guided"}})()
            return Run()
    state.runtime_store = Runtime()
    result = state.teaching_dashboard(owner_id="student")
    assert result["authority"] == "WorkflowRuntime"
    assert result["summary"] == {"total": 3, "active": 1, "succeeded": 1, "failed": 1}
    assert result["polling"]["recommended_seconds"] == 2
    assert result["runs"][0]["experiment_id"] == "exp-1"
    assert result["runs"][0]["agent_action"] == "waiting for Runtime worker"
