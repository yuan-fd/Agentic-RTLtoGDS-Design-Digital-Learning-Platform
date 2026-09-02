from openroad_platform_scheduler.l1_loop_store import L1LoopStore
import pytest
def test_loop_store_is_append_then_single_submit(tmp_path):
    store=L1LoopStore(tmp_path/"loop.sqlite"); store.propose("plan-1","trace-1","goal-1","state-1",{"call_id":"call-1"})
    store.prepare_execution("plan-1", {"call_id":"call-1"})
    store.record_receipt("plan-1", {"result":{"run_id":"run-1"}})
    assert store.get("plan-1")["run_id"] == "run-1"
    with pytest.raises(ValueError): store.record_receipt("plan-1", {"result":{"run_id":"run-2"}})

def test_parameter_proposal_survives_store_reopen_and_commits_once(tmp_path):
    path=tmp_path/"loop.sqlite"; initial=L1LoopStore(path); initial.propose("plan-1","trace-1","goal-1","state-1",{}); initial.save_proposal("proposal-1","trace-1","goal-1","state-1",{"density":0.7})
    reopened=L1LoopStore(path)
    assert reopened.reserve_proposal("proposal-1","trace-1","goal-1","state-1","plan-1") == {"density":0.7}
    reopened.prepare_execution("plan-1", {"call_id":"call-1"})
    reopened.record_receipt("plan-1", {"result":{"run_id":"run-1"}})
    reopened.propose("plan-2","trace-1","goal-1","state-1",{})
    with pytest.raises(ValueError): reopened.reserve_proposal("proposal-1","trace-1","goal-1","state-1","plan-2")

def test_reservation_releases_before_submit_and_persists_canonical_call(tmp_path):
    store=L1LoopStore(tmp_path/"loop.sqlite")
    store.save_proposal("proposal-1","trace-1","goal-1","state-1",{"density":0.7})
    store.propose("plan-1","trace-1","goal-1","state-1",{"call_id":"raw"})
    assert store.reserve_proposal("proposal-1","trace-1","goal-1","state-1","plan-1") == {"density":0.7}
    store.prepare_execution("plan-1", {"call_id":"canonical","arguments":{"parameter_patch":{"density":0.7},"proposal_id":"proposal-1"}})
    plan=store.get("plan-1")
    assert plan["call"]["call_id"] == "canonical" and plan["submitted_call_sha256"]
    store.release_reservation("plan-1")
    store.propose("plan-2","trace-1","goal-1","state-1",{})
    assert store.reserve_proposal("proposal-1","trace-1","goal-1","state-1","plan-2") == {"density":0.7}

def test_receipt_commit_consumes_reserved_proposal_atomically(tmp_path):
    store=L1LoopStore(tmp_path/"loop.sqlite")
    store.save_proposal("proposal-1","trace-1","goal-1","state-1",{"density":0.7})
    store.propose("plan-1","trace-1","goal-1","state-1",{})
    store.reserve_proposal("proposal-1","trace-1","goal-1","state-1","plan-1")
    store.prepare_execution("plan-1", {"call_id":"canonical"})
    store.record_receipt("plan-1", {"result":{"run_id":"run-1"}})
    assert store.get("plan-1")["status"] == "submitted"
    store.propose("plan-2","trace-1","goal-1","state-1",{})
    with pytest.raises(ValueError): store.reserve_proposal("proposal-1","trace-1","goal-1","state-1","plan-2")
