from __future__ import annotations

from dataclasses import dataclass

import pytest

from apps.l1_workbench.l2_campaign_worker import advance_eligible_once
from apps.l1_workbench.service import WorkbenchService
from openroad_platform_contracts.l1_goal_draft import ClarificationField


@dataclass
class _Checkpoints:
    records: dict[str, dict]

    def get(self, pipeline_id):
        return self.records[pipeline_id]

    def list(self, *, pipeline_kind, limit):
        assert pipeline_kind == "orfs-agent-full-campaign-v1"
        assert limit == 1000
        return list(self.records.values())


class _Campaign:
    def __init__(self, checkpoints):
        self.checkpoints = checkpoints
        self.calls = []

    def advance(self, pipeline_id, *, execute, max_parallel):
        self.calls.append((pipeline_id, execute, max_parallel))
        current = self.checkpoints.records[pipeline_id]
        updated = {**current, "revision": current["revision"] + 1,
                   "state": {**current["state"], "status": "initialization_running"}}
        self.checkpoints.records[pipeline_id] = updated
        return updated


class _Service:
    def __init__(self):
        records = {
            "active": {"pipeline_id": "active", "revision": 3,
                       "state": {"status": "initialization_pending"}},
            "unconfigured": {"pipeline_id": "unconfigured", "revision": 0,
                             "state": {"status": "authorized"}},
            "done": {"pipeline_id": "done", "revision": 9,
                     "state": {"status": "completed"}},
        }
        self.l2_checkpoints = _Checkpoints(records)
        self.l2_campaign = _Campaign(self.l2_checkpoints)


def test_worker_executes_only_configured_nonterminal_campaigns():
    service = _Service()
    result = advance_eligible_once(service, pipeline_id=None, max_parallel=4)
    assert service.l2_campaign.calls == [("active", True, 4)]
    assert result == [{"pipeline_id": "active", "revision": 4,
                       "before": "initialization_pending",
                       "after": "initialization_running"}]


def test_worker_can_target_one_pipeline_and_rejects_invalid_parallelism():
    service = _Service()
    assert advance_eligible_once(service, pipeline_id="unconfigured", max_parallel=1) == []
    with pytest.raises(ValueError, match="at least one"):
        advance_eligible_once(service, pipeline_id="active", max_parallel=0)


def test_workbench_l2_monitor_returns_only_session_bound_checkpoints(tmp_path):
    service = WorkbenchService(tmp_path)
    session = service.start("Run one bounded flow")
    session = service.answer(session.session_id, [{
        "question_id": "objective-1", "field": ClarificationField.OBJECTIVE.value,
        "value": "confirm",
    }])
    checkpoint = service.l2_checkpoints.create_or_get(
        pipeline_kind="a2-orfo-campaign-v1", subject_id="bound",
        owner_id=None, initial_state={
            "status": "authorized",
            "goal": {"goal_id": session.goal_id, "project_id": "workbench-project"},
        })
    service.l2_checkpoints.create_or_get(
        pipeline_kind="a2-orfo-campaign-v1", subject_id="other",
        owner_id=None, initial_state={
            "status": "authorized", "goal": {"goal_id": "another-goal"},
        })
    assert service.l2_status(session.session_id, checkpoint["pipeline_id"])[
        "pipeline_id"] == checkpoint["pipeline_id"]
    assert [item["pipeline_id"] for item in service.l2_list(session.session_id)] == [
        checkpoint["pipeline_id"]]
