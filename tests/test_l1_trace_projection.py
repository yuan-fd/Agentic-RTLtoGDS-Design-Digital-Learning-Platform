import hashlib, os
from openroad_platform_scheduler.l1_trace_projection import L1TraceReader, list_trace_ids, project_trace
from openroad_platform_scheduler.l1_trace_store import L1TraceStore
from openroad_platform_scheduler.l1_trace_service import L1TraceService
from openroad_platform_contracts.l1_goal_draft import GoalDraft, GoalIntent

def test_trace_projection_is_read_only_durable_facts(tmp_path):
    store=L1TraceStore(tmp_path/'trace.sqlite'); service=L1TraceService(store)
    service.record_draft('trace-1',GoalDraft('draft-1','diagnose timing',GoalIntent.DIAGNOSE))
    reader=L1TraceReader(tmp_path/'trace.sqlite'); before=(hashlib.sha256((tmp_path/'trace.sqlite').read_bytes()).hexdigest(),os.stat(tmp_path/'trace.sqlite').st_mtime_ns)
    assert list_trace_ids(reader)==('trace-1',)
    view=project_trace(reader,'trace-1')
    assert before==(hashlib.sha256((tmp_path/'trace.sqlite').read_bytes()).hexdigest(),os.stat(tmp_path/'trace.sqlite').st_mtime_ns)
    assert view['events'][0]['kind']=='goal_drafted' and 'hidden_reasoning' not in str(view)

def test_trace_reader_never_creates_missing_database(tmp_path):
    import pytest
    missing=tmp_path/'missing.sqlite'
    with pytest.raises(FileNotFoundError): L1TraceReader(missing)
    assert not missing.exists()
