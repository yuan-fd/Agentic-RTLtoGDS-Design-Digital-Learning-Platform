from openroad_platform_scheduler.l1_loop_store import L1LoopStore
import pytest
def test_loop_store_is_append_then_single_submit(tmp_path):
    store=L1LoopStore(tmp_path/"loop.sqlite"); store.propose("plan-1","trace-1","goal-1","state-1",{"call_id":"call-1"})
    store.record_receipt("plan-1", {"result":{"run_id":"run-1"}})
    assert store.get("plan-1")["run_id"] == "run-1"
    with pytest.raises(ValueError): store.record_receipt("plan-1", {"result":{"run_id":"run-2"}})

def test_parameter_proposal_survives_store_reopen_and_consumes_once(tmp_path):
    path=tmp_path/"loop.sqlite"; initial=L1LoopStore(path); initial.propose("plan-1","trace-1","goal-1","state-1",{}); initial.save_proposal("proposal-1","trace-1","goal-1","state-1",{"density":0.7})
    reopened=L1LoopStore(path)
    assert reopened.consume_proposal("proposal-1","trace-1","goal-1","state-1","plan-1") == {"density":0.7}
    with pytest.raises(ValueError): reopened.consume_proposal("proposal-1","trace-1","goal-1","state-1","plan-2")
