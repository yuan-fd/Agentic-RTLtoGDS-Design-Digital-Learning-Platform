import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "apps/m3_orfs_comparison/src"))

from openroad_app_m3.service import M3Service


class V2:
    def session(self):
        return {"user": {"id": "teacher-1"}}


def test_m3_records_fixed_protocol_and_both_failures_without_shortening_protocol():
    service = M3Service.in_memory(V2())
    result = service.create("teacher-1", {"rtl_input_id": "input-1", "pdk": "nangate45", "sdc": "create_clock", "evaluator": "orfs-evaluator-v1", "search_space": {"utilization": [40, 60]}, "budget": {"seconds": 60}, "stop_condition": {"max_trials": 4}})
    result = service.run(result["comparison_id"], "teacher-1")
    assert result["search_space"] == {"utilization": [40, 60]}
    assert result["strategies"]["baseline"]["status"] == "blocked"
    assert result["strategies"]["orfs_agent"]["status"] == "blocked"
    assert result["strategies"]["baseline"]["failures"]
    assert result["strategies"]["orfs_agent"]["failures"]
