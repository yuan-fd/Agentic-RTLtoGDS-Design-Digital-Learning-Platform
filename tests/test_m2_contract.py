import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "apps/m2_rtl_comparison/src"))

from openroad_app_m2.service import M2Service


class V2:
    def session(self):
        return {"user": {"id": "teacher-1"}}

    def upload_rtl(self, source):
        return {"input_id": "input-" + str(len(source))}

    def submit(self, task, key):
        return "run-unused"


def test_m2_keeps_two_generators_independent_without_fallback():
    service = M2Service.in_memory(V2())
    record = service.create("teacher-1", {"spec_id": "spec-a", "verification_id": "verify-a", "pdk": "nangate45"})
    record["candidate_sources"] = {"direct_llm": "module direct; endmodule"}
    service.store.put(record["comparison_id"], record)
    result = service.run(record["comparison_id"], "teacher-1")
    assert result["candidates"]["direct_llm"]["status"] == "submitted"
    assert result["candidates"]["rtlscout"]["status"] == "toolchain_unavailable"
    assert result["candidates"]["rtlscout"]["run_ids"] == []
