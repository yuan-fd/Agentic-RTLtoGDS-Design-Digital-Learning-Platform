from dataclasses import dataclass

import pytest

from apps.l1_workbench.a2_campaign_worker import advance_eligible_a2_once


@dataclass
class _Checkpoints:
    records: dict

    def get(self, pipeline_id):
        return self.records[pipeline_id]

    def list(self, *, pipeline_kind, limit):
        assert pipeline_kind == "a2-orfo-campaign-v1" and limit == 1000
        return list(self.records.values())


class _Campaign:
    def __init__(self, checkpoints):
        self.checkpoints = checkpoints; self.calls = []

    def advance(self, pipeline_id, *, execute, max_parallel):
        self.calls.append((pipeline_id, execute, max_parallel))
        current = self.checkpoints.records[pipeline_id]
        updated = {**current, "revision": current["revision"] + 1,
                   "state": {**current["state"], "status": "bootstrap_running"}}
        self.checkpoints.records[pipeline_id] = updated
        return updated


class _Service:
    def __init__(self):
        records = {
            "active": {"pipeline_id": "active", "revision": 1,
                       "state": {"status": "bootstrap_pending"}},
            "authorized": {"pipeline_id": "authorized", "revision": 0,
                           "state": {"status": "authorized"}},
            "done": {"pipeline_id": "done", "revision": 8,
                     "state": {"status": "completed"}},
        }
        self.l2_checkpoints = _Checkpoints(records)
        self.l2_campaign = _Campaign(self.l2_checkpoints)


def test_a2_worker_executes_only_configured_nonterminal_campaigns():
    service = _Service()
    result = advance_eligible_a2_once(service, pipeline_id=None, max_parallel=4)
    assert service.l2_campaign.calls == [("active", True, 4)]
    assert result == [{"pipeline_id": "active", "revision": 2,
                       "before": "bootstrap_pending", "after": "bootstrap_running"}]


def test_a2_worker_can_target_and_rejects_bad_parallelism():
    service = _Service()
    assert advance_eligible_a2_once(
        service, pipeline_id="authorized", max_parallel=1) == []
    with pytest.raises(ValueError, match="at least one"):
        advance_eligible_a2_once(service, pipeline_id="active", max_parallel=0)
