import json
import sys
import threading
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).parents[1] / "apps/m3_orfs_comparison/src"))

from openroad_app_m3.server import build_server
from openroad_app_m3.service import M3Service


class V2:
    def with_token(self, token): return self
    def session(self): return {"user": {"id": "teacher-1"}}


def test_m3_http_contract():
    server = build_server("127.0.0.1", 0, M3Service.in_memory(V2()))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = "http://127.0.0.1:" + str(server.server_address[1])
        payload = {"rtl_input_id": "input-1", "pdk": "nangate45", "sdc": "create_clock", "evaluator": "v1", "search_space": {"u": [40, 60]}, "budget": {"seconds": 20}, "stop_condition": {"max_trials": 2}}
        with urlopen(Request(base + "/api/m3/comparisons", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})) as response:
            result = json.loads(response.read())
        assert result["comparison"]["strategies"]["orfs_agent"]["strategy"] == "orfs_agent"
    finally:
        server.shutdown()
        server.server_close()
