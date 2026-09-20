import json
import sys
import threading
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).parents[1] / "apps/m2_rtl_comparison/src"))

from openroad_app_m2.server import build_server
from openroad_app_m2.service import M2Service


class V2:
    def with_token(self, token): return self
    def session(self): return {"user": {"id": "teacher-1"}}


def test_m2_http_contract():
    server = build_server("127.0.0.1", 0, M2Service.in_memory(V2()))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = "http://127.0.0.1:" + str(server.server_address[1])
        body = json.dumps({"spec_id": "spec-a", "verification_id": "verify-a", "pdk": "nangate45"}).encode()
        with urlopen(Request(base + "/api/m2/comparisons", data=body, headers={"Content-Type": "application/json"})) as response:
            result = json.loads(response.read())
        assert result["comparison"]["candidates"]["direct_llm"]["generator"] == "direct_llm"
    finally:
        server.shutdown()
        server.server_close()
