import sys
import json
import threading
from pathlib import Path
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).parents[1] / "apps/m1_rtl_to_gds/src"))

from openroad_app_m1.server import build_server
from openroad_app_m1.service import M1Service
from openroad_app_m1.v2_client import V2ClientError


class UnauthenticatedV2:
    def health(self):
        return {"ok": True, "status": "ok"}

    def session(self):
        raise V2ClientError("authentication required", status=401)

    def with_token(self, token):
        return self


def test_m1_health_is_public_before_v2_login():
    server = build_server("127.0.0.1", 0, M1Service.in_memory(), UnauthenticatedV2())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f"http://127.0.0.1:{server.server_address[1]}/api/m1/health") as response:
            payload = json.loads(response.read())
        assert payload["status"] == "ok"
        assert payload["identity"] is None
    finally:
        server.shutdown()
        server.server_close()
