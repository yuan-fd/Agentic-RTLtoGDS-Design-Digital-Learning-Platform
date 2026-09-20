import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "apps/m4_script_lab/src"))

from openroad_app_m4.service import M4Service


class V2:
    def session(self):
        return {"user": {"id": "teacher-1"}}

    def upload(self, source):
        return "input-patch"

    def submit(self, task, key):
        return "run-patch"


def test_m4_requires_confirmation_before_v2_execution():
    service = M4Service.in_memory(V2())
    proposal = service.create("teacher-1", {"recipe_id": "course-counter-nangate45-v1", "touched_paths": ["flow.tcl"], "diff": "+set_app_var foo bar"})
    try:
        service.run(proposal["proposal_id"], "teacher-1")
    except ValueError as exc:
        assert "confirmed" in str(exc)
    else:
        raise AssertionError("unconfirmed proposal executed")
    confirmed = service.confirm(proposal["proposal_id"], "teacher-1")
    result = service.run(confirmed["proposal_id"], "teacher-1")
    assert result["state"] == "submitted"
    rejected = service.create("teacher-1", {"recipe_id": "course-counter-nangate45-v1", "touched_paths": ["server.py"], "diff": "+bad"})
    assert rejected["state"] == "rejected"
