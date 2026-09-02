from openroad_platform_scheduler.l1_trace_projection import list_trace_ids, project_trace
from openroad_platform_scheduler.l1_trace_store import L1TraceStore
from openroad_platform_scheduler.l1_trace_service import L1TraceService
from openroad_platform_contracts.l1_goal_draft import GoalDraft, GoalIntent

def test_trace_projection_is_read_only_durable_facts(tmp_path):
    store=L1TraceStore(tmp_path/'trace.sqlite'); service=L1TraceService(store)
    service.record_draft('trace-1',GoalDraft('draft-1','diagnose timing',GoalIntent.DIAGNOSE))
    assert list_trace_ids(store)==('trace-1',)
    view=project_trace(store,'trace-1')
    assert view['events'][0]['kind']=='goal_drafted' and 'hidden_reasoning' not in str(view)
