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


def test_teaching_campaign_detail_projects_runtime_batch_roles():
    state = object.__new__(ApiState)
    state.pipeline_checkpoints = type("P", (), {"list": lambda self, **kwargs: []})()
    state.list_runtime_runs = lambda **kwargs: {"runs": [
        {"run_id": "b", "status": "succeeded"},
        {"run_id": "c", "status": "running"},
    ]}
    class Runtime:
        @staticmethod
        def get_run(run_id):
            role = "baseline" if run_id == "b" else "candidate"
            return type("Run", (), {"task_spec": type("Task", (), {"labels": {
                "teaching_batch_id": "batch-1", "teaching_batch_role": role}})()})()
    state.runtime_store = Runtime()
    detail = state.teaching_campaign_detail("batch-1", owner_id="student")
    assert detail["kind"] == "batch" and detail["status"] == "running"
    assert [item["run_id"] for item in detail["baseline"]] == ["b"]
    assert [item["run_id"] for item in detail["candidates"]] == ["c"]


def test_teaching_learning_projection_requires_runtime_evidence():
    from apps.api.services.teaching_sessions import TeachingSessions
    service = TeachingSessions(None, None)
    service.get = lambda sid, owner: {"state": {"status": "observed", "evidence": [{"ref": "run:x"}]}, "runtime": {"run": {"status": "succeeded"}}}
    result = service.learning("s1", "u1")
    assert result["promotion"]["status"] == "eligible_for_review"
    service.get = lambda sid, owner: {"state": {"status": "observed", "evidence": []}, "runtime": {"run": {"status": "succeeded"}}}
    assert service.learning("s1", "u1")["promotion"]["status"] == "not_eligible"
