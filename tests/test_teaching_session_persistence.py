import pytest

from apps.l1_workbench.service import WorkbenchService


def test_teaching_context_survives_restart_and_reaches_baseline_and_candidate(tmp_path):
    context = {"objective": "Measure area", "hypothesis": "Density changes routing"}
    service = WorkbenchService(tmp_path)
    session = service.start("Run one flow", teaching_mode="challenge", teaching_context=context)
    sid = session.session_id
    service.answer(sid, [{"question_id": "objective-1", "field": "objective", "value": "one run"}])
    restored = WorkbenchService(tmp_path)
    result, _ = restored.execute(sid, "Run the baseline")
    labels = restored.runtime.store.get_run(result["run_id"]).task_spec.labels
    assert labels["teaching_mode"] == "challenge"
    assert labels["teaching_hypothesis"] == context["hypothesis"]
    assert labels["teaching_objective"] == context["objective"]
    proposal = restored.set_flow_params(sid, {"place_density": .5}, "Try a density")
    candidate, _ = restored.run_candidate(sid, proposal["proposal_id"], "Compare density")
    assert restored.runtime.store.get_run(candidate["run_id"]).task_spec.labels["teaching_mode"] == "challenge"


def test_workbench_rejects_design_context_that_does_not_match_bound_rtl(tmp_path):
    service = WorkbenchService(tmp_path)
    with pytest.raises(ValueError, match="design"):
        service.start("Run UART", teaching_mode="open", teaching_context={"design_id": "uart"})
