import json
import sys
import threading
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).parents[1] / "apps/m4_script_lab/src"))

from openroad_app_m4.server import build_server
from openroad_app_m4.service import M4Service


class V2:
    def with_token(self, token): return self
    def session(self): return {"user": {"id": "teacher-1"}}


def test_m4_http_contract():
    server = build_server("127.0.0.1", 0, M4Service.in_memory(V2()))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = "http://127.0.0.1:" + str(server.server_address[1])
        payload = {"recipe_id": "course-counter-nangate45-v1", "touched_paths": ["flow.tcl"], "diff": "+set_app_var foo bar"}
        with urlopen(Request(base + "/api/m4/proposals", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})) as response:
            result = json.loads(response.read())
        proposal_id = result["proposal"]["proposal_id"]
        with urlopen(Request(base + "/api/m4/proposals/" + proposal_id + "/confirm", data=b"{}", headers={"Content-Type": "application/json"})) as response:
            confirmed = json.loads(response.read())
        assert confirmed["proposal"]["state"] == "confirmed"
    finally:
        server.shutdown()
        server.server_close()
