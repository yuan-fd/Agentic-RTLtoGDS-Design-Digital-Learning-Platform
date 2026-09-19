import json
import sys
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


M1_SRC = Path(__file__).parents[1] / "apps/m1_rtl_to_gds/src"
if str(M1_SRC) not in sys.path:
    sys.path.insert(0, str(M1_SRC))

from openroad_app_m1.models import VerificationStatus  # noqa: E402
from openroad_app_m1.server import build_server  # noqa: E402
from openroad_app_m1.service import M1Service  # noqa: E402


class FakeV2:
    def __init__(self):
        self.submissions = []
        self.user_id = "user-1"

    def health(self):
        return {"ok": True, "status": "ok"}

    def session(self):
        return {"user_id": self.user_id, "username": "student"}

    def upload_rtl(self, source):
        return {"input_id": f"input-{len(source)}"}

    def plugins(self):
        return [
            {"plugin_id": "rtl-verify", "admission": "admitted", "executable": True,
             "capabilities": ["eda.rtl.verify"]},
            {"plugin_id": "rtl-sim", "admission": "admitted", "executable": True,
             "capabilities": ["eda.rtl.simulate"]},
        ]

    def submit(self, task, *, idempotency_key):
        self.submissions.append((task, idempotency_key))
        return {"run": {"run_id": f"run-{len(self.submissions)}"}}

    def run(self, run_id):
        return {"run": {"run_id": run_id, "status": "queued"}}


def spec_payload():
    return {
        "spec": {
            "schema_version": 1,
            "spec_id": "spec-counter",
            "design_id": "course-counter",
            "top": "counter",
            "functionality": "A synchronous counter with reset and enable.",
            "objective": "Teach sequential RTL and a bounded RTL-to-GDS flow.",
            "ports": [
                {"schema_version": 1, "name": "clk", "direction": "input", "width": 1},
                {"schema_version": 1, "name": "rst_n", "direction": "input", "width": 1},
                {"schema_version": 1, "name": "enable", "direction": "input", "width": 1},
                {"schema_version": 1, "name": "q", "direction": "output", "width": 8},
            ],
            "clock": "clk",
            "reset": "rst_n",
            "constraints": {"clock_period_ns": 5.0},
            "acceptance_criteria": ["q increments on each enabled rising edge"],
        },
    }


def request(base, method, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    request = Request(base + path, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())


def running_server():
    fake = FakeV2()
    server = build_server("127.0.0.1", 0, M1Service.in_memory(), fake)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, fake, f"http://127.0.0.1:{server.server_address[1]}"


def test_m1_http_api_freezes_spec_and_creates_v2_staged_rtl_version():
    server, fake, base = running_server()
    try:
        status, health = request(base, "GET", "/api/m1/health")
        assert status == 200
        assert health["status"] == "ok"
        assert health["identity"] == "user-1"

        status, created = request(base, "POST", "/api/m1/specs", spec_payload())
        assert status == 201
        spec_id = created["session"]["spec_id"]
        assert created["session"]["owner_id"] == "user-1"

        status, frozen = request(base, "POST", f"/api/m1/specs/{spec_id}/freeze", {})
        assert status == 200
        assert frozen["session"]["state"] == "frozen"

        status, version = request(
            base, "POST", f"/api/m1/specs/{spec_id}/rtl",
            {"rtl_source": "module counter; endmodule", "generator": "direct_llm"},
        )
        assert status == 201
        assert version["rtl_version"]["source_ref"].startswith("input:")
        assert version["rtl_version"]["generator"] == "direct_llm"
    finally:
        server.shutdown()
        server.server_close()


def test_m1_http_api_rejects_client_identity_and_unverified_gds_submission():
    server, fake, base = running_server()
    try:
        invalid = spec_payload()
        invalid["owner_id"] = "attacker-controlled"
        status, error = request(base, "POST", "/api/m1/specs", invalid)
        assert status == 422
        assert error["error"]["message"] == "owner_id is derived from the v2 identity"

        status, created = request(base, "POST", "/api/m1/specs", spec_payload())
        spec_id = created["session"]["spec_id"]
        request(base, "POST", f"/api/m1/specs/{spec_id}/freeze", {})
        _, version = request(
            base, "POST", f"/api/m1/specs/{spec_id}/rtl",
            {"rtl_source": "module counter; endmodule", "generator": "direct_llm"},
        )
        version_id = version["rtl_version"]["version_id"]

        status, error = request(
            base, "POST", f"/api/m1/rtl/{version_id}/gds", {"pdk": "nangate45"}
        )
        assert status == 422
        assert error["error"]["code"] == "VALIDATION_ERROR"
        assert not fake.submissions
    finally:
        server.shutdown()
        server.server_close()


def test_m1_http_api_returns_v2_run_observation_without_local_execution():
    server, fake, base = running_server()
    try:
        status, result = request(base, "GET", "/api/m1/runs/run-42")
        assert status == 200
        assert result["run"]["run_id"] == "run-42"
        assert result["run"]["status"] == "queued"
    finally:
        server.shutdown()
        server.server_close()


def test_m1_http_api_rejects_a_different_v2_identity_from_mutating_spec_state():
    server, fake, base = running_server()
    try:
        _, created = request(base, "POST", "/api/m1/specs", spec_payload())
        spec_id = created["session"]["spec_id"]
        fake.user_id = "user-2"
        status, error = request(base, "POST", f"/api/m1/specs/{spec_id}/freeze", {})
        assert status == 403
        assert error["error"]["code"] == "FORBIDDEN"
    finally:
        server.shutdown()
        server.server_close()
