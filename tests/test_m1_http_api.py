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
        self.auth_calls = []

    def health(self):
        return {"ok": True, "status": "ok"}

    def session(self):
        return {"user": {"id": self.user_id, "username": "student", "role": "member"}}

    def login(self, username, password):
        self.auth_calls.append(("login", username, password))
        return {"token": "token-1", "session": {"user": {"id": self.user_id}}}

    def logout(self):
        self.auth_calls.append(("logout",))
        return {"ok": True}

    def with_token(self, token):
        return self

    def upload_rtl(self, source):
        input_id = f"input-{len(source)}"
        self.inputs = getattr(self, "inputs", {})
        self.inputs[input_id] = source
        return {"input_id": input_id}

    def input(self, input_id):
        source = self.inputs[input_id]
        return {"input": {"input_id": input_id}, "content": source}

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

    def timeline(self, run_id):
        return [{"run_id": run_id, "event_type": "stage.started"}]

    def artifacts(self, run_id):
        return [{"artifact_id": "artifact-1", "kind": "gds", "sha256": "a" * 64}]

    def metrics(self, run_id):
        return [{"name": "area", "value": 1.0, "unit": "um2"}]

    def artifact_preview(self, run_id, artifact_id):
        return {"status": "ready", "artifact_id": artifact_id, "mime_type": "image/svg+xml", "content": "<svg/>"}

    def artifact_excerpt(self, run_id, artifact_id):
        return {"artifact_id": artifact_id, "text": "module counter;\nendmodule"}


class FakeLLM:
    def generate(self, payload):
        return "module counter(input logic clk, input logic rst_n, input logic enable, output logic [7:0] q); endmodule"

    def assess(self, description):
        return {"status": "needs_clarification", "questions": ["What is the input sequence?"]}


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


def request(base, method, path, payload=None, *, raw=False):
    data = None if payload is None else json.dumps(payload).encode()
    request = Request(base + path, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urlopen(request, timeout=5) as response:
            body = response.read()
            return response.status, body.decode() if raw else json.loads(body)
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())


def running_server():
    fake = FakeV2()
    server = build_server("127.0.0.1", 0, M1Service.in_memory(), fake, llm_provider=FakeLLM())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, fake, f"http://127.0.0.1:{server.server_address[1]}"


def test_m1_http_api_freezes_spec_and_creates_v2_staged_rtl_version():
    server, fake, base = running_server()
    try:
        status, page = request(base, "GET", "/", raw=True)
        assert status == 200
        assert "RTL-to-GDS Workbench" in page

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
        status, submitted = request(
            base, "POST", f"/api/m1/rtl/{version['rtl_version']['version_id']}/verify", {}
        )
        assert status == 202
        assert submitted["state"] == "submitted"
    finally:
        server.shutdown()
        server.server_close()


def test_m1_http_api_generates_rtl_through_the_direct_llm_boundary():
    server, fake, base = running_server()
    try:
        _, created = request(base, "POST", "/api/m1/specs", spec_payload())
        spec_id = created["session"]["spec_id"]
        request(base, "POST", f"/api/m1/specs/{spec_id}/freeze", {})

        status, generated = request(base, "POST", f"/api/m1/specs/{spec_id}/generate", {})

        assert status == 201
        assert generated["rtl_version"]["generator"] == "direct_llm"
        assert generated["rtl_version"]["source_ref"].startswith("input:input-")
    finally:
        server.shutdown()
        server.server_close()


def test_m1_http_api_assesses_natural_language_before_freeze():
    server, fake, base = running_server()
    try:
        status, created = request(base, "POST", "/api/m1/specs", {"description": "sequence detector"})

        assert status == 201
        assert created["session"]["state"] == "needs_clarification"
        assert created["session"]["clarification_questions"] == ["What is the input sequence?"]
    finally:
        server.shutdown()
        server.server_close()


def test_m1_http_api_reads_rtl_and_v2_observations():
    server, fake, base = running_server()
    try:
        _, created = request(base, "POST", "/api/m1/specs", spec_payload())
        spec_id = created["session"]["spec_id"]
        request(base, "POST", f"/api/m1/specs/{spec_id}/freeze", {})
        _, generated = request(base, "POST", f"/api/m1/specs/{spec_id}/generate", {})
        version_id = generated["rtl_version"]["version_id"]

        status, rtl = request(base, "GET", f"/api/m1/rtl/{version_id}")
        assert status == 200
        assert "module counter" in rtl["source"]

        assert request(base, "GET", "/api/m1/runs/run-42/timeline")[1]["timeline"]
        assert request(base, "GET", "/api/m1/runs/run-42/artifacts")[1]["artifacts"]
        assert request(base, "GET", "/api/m1/runs/run-42/metrics")[1]["metrics"]
        assert len(request(base, "GET", "/api/m1/catalog/courses")[1]["courses"]) == 10
        assert len(request(base, "GET", "/api/m1/catalog/pdks")[1]["capabilities"]) == 30
    finally:
        server.shutdown()
        server.server_close()


def test_m1_http_api_proxies_v2_artifact_preview():
    server, fake, base = running_server()
    try:
        status, preview = request(
            base, "GET", "/api/m1/runs/run-42/artifacts/artifact-1/preview"
        )
        assert status == 200
        assert preview["preview"]["status"] == "ready"
        assert preview["preview"]["artifact_id"] == "artifact-1"
    finally:
        server.shutdown()
        server.server_close()


def test_m1_http_api_proxies_v2_artifact_excerpt():
    server, fake, base = running_server()
    try:
        status, excerpt = request(
            base, "GET", "/api/m1/runs/run-42/artifacts/artifact-1/excerpt"
        )
        assert status == 200
        assert excerpt["excerpt"]["text"].startswith("module counter")
    finally:
        server.shutdown()
        server.server_close()


def test_m1_http_api_exposes_login_session_and_logout_boundaries():
    server, fake, base = running_server()
    try:
        status, login = request(
            base, "POST", "/api/auth/login",
            {"username": "student", "password": "secret"},
        )
        assert status == 200
        assert login["session"]["user"]["id"] == "user-1"
        assert fake.auth_calls == [("login", "student", "secret")]
        status, session = request(base, "GET", "/api/auth/session")
        assert status == 200
        assert session["session"]["user"]["id"] == "user-1"
        status, logged_out = request(base, "POST", "/api/auth/logout", {})
        assert status == 200
        assert logged_out["ok"] is True
        assert fake.auth_calls[-1] == ("logout",)
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
