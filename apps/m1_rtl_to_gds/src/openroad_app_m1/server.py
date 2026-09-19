"""HTTP boundary for the independent M1 teaching application."""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from openroad_platform_contracts.rtl_frontend import SpecIR, VerificationPackage

from .generator import CodexCLIProvider, DirectLLMGenerator
from .service import M1Service
from .v2_client import V2ClientError, V2Unavailable


WEB_ROOT = Path(__file__).parents[2] / "web"
MAX_BODY_BYTES = 2 * 1024 * 1024


class AuthorizationError(PermissionError):
    """The v2 identity is valid but does not own the requested M1 record."""


def build_server(host: str, port: int, service: M1Service, v2_client: Any,
                 *, llm_provider: Any | None = None) -> ThreadingHTTPServer:
    provider = llm_provider or CodexCLIProvider()
    generator = DirectLLMGenerator(service)

    class M1Handler(BaseHTTPRequestHandler):
        server_version = "OpenROAD-M1/0.1"

        def do_GET(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            try:
                if path == "/api/m1/health":
                    self._json(HTTPStatus.OK, self._health())
                    return
                if path.startswith("/api/m1/rtl/") and "/" not in path.removeprefix("/api/m1/rtl/"):
                    version_id = path.removeprefix("/api/m1/rtl/")
                    self._owned_version(version_id)
                    version = service.get_rtl_version(version_id)
                    source = v2_client.input(version.source_ref.removeprefix("input:"))
                    self._json(HTTPStatus.OK, {
                        "rtl_version": version.to_dict(),
                        "source": source["content"],
                    })
                    return
                if path.startswith("/api/m1/runs/"):
                    if path.endswith("/excerpt"):
                        excerpt_path = path.removesuffix("/excerpt")
                        prefix, artifact_id = excerpt_path.removeprefix("/api/m1/runs/").rsplit("/artifacts/", 1)
                        if not prefix or not artifact_id:
                            raise ValueError("run_id and artifact_id are required")
                        self._json(HTTPStatus.OK, {
                            "excerpt": v2_client.artifact_excerpt(prefix, artifact_id)
                        })
                        return
                    if path.endswith("/preview"):
                        preview_path = path.removesuffix("/preview")
                        prefix, artifact_id = preview_path.removeprefix("/api/m1/runs/").rsplit("/artifacts/", 1)
                        if not prefix or not artifact_id:
                            raise ValueError("run_id and artifact_id are required")
                        self._json(HTTPStatus.OK, {
                            "preview": v2_client.artifact_preview(prefix, artifact_id)
                        })
                        return
                    if path.endswith("/timeline"):
                        run_id = path.removeprefix("/api/m1/runs/").removesuffix("/timeline")
                        self._json(HTTPStatus.OK, {"timeline": v2_client.timeline(run_id)})
                        return
                    if path.endswith("/artifacts"):
                        run_id = path.removeprefix("/api/m1/runs/").removesuffix("/artifacts")
                        self._json(HTTPStatus.OK, {"artifacts": v2_client.artifacts(run_id)})
                        return
                    if path.endswith("/metrics"):
                        run_id = path.removeprefix("/api/m1/runs/").removesuffix("/metrics")
                        self._json(HTTPStatus.OK, {"metrics": v2_client.metrics(run_id)})
                        return
                    run_id = path.removeprefix("/api/m1/runs/")
                    if not run_id or "/" in run_id:
                        raise ValueError("run_id is required")
                    observation = v2_client.run(run_id)
                    run = observation.get("run", observation)
                    service.observe_run(run_id, run.get("status"))
                    if run.get("status") == "succeeded" and run.get("task_id", "").startswith("m1-gds-"):
                        version_id = run["task_id"].removeprefix("m1-gds-").rsplit("-", 1)[0]
                        service.record_gds_evidence(
                            version_id, run_id, v2_client.artifacts(run_id),
                            pdk=run["task_id"].rsplit("-", 1)[1],
                        )
                    self._json(HTTPStatus.OK, {"run": run})
                    return
                if path.startswith("/api/m1/evidence/"):
                    evidence_id = path.removeprefix("/api/m1/evidence/")
                    evidence = service.get_evidence(evidence_id)
                    if evidence.owner_id != self._owner_id():
                        raise AuthorizationError("evidence belongs to another v2 identity")
                    self._json(HTTPStatus.OK, {"evidence": evidence.to_dict()})
                    return
                if path in {"/", "/index.html"}:
                    self._file(WEB_ROOT / "index.html", "text/html; charset=utf-8")
                    return
                if path == "/app.css":
                    self._file(WEB_ROOT / "app.css", "text/css; charset=utf-8")
                    return
                if path == "/app.js":
                    self._file(WEB_ROOT / "app.js", "text/javascript; charset=utf-8")
                    return
                self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "resource not found")
            except (AuthorizationError, PermissionError, KeyError, ValueError,
                    V2Unavailable, V2ClientError) as exc:
                self._handle_error(exc)

        def do_POST(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            try:
                payload = self._body()
                if path == "/api/m1/specs":
                    self._create_spec(payload)
                    return
                if path.startswith("/api/m1/specs/") and path.endswith("/freeze"):
                    spec_id = path.removeprefix("/api/m1/specs/").removesuffix("/freeze")
                    self._owned_spec(spec_id)
                    session = service.freeze_spec(spec_id)
                    self._register_teaching_package(session)
                    self._json(HTTPStatus.OK, {"session": session.to_dict()})
                    return
                if path.startswith("/api/m1/specs/") and path.endswith("/generate"):
                    spec_id = path.removeprefix("/api/m1/specs/").removesuffix("/generate")
                    self._owned_spec(spec_id)
                    version = generator.generate(spec_id, provider, v2_client)
                    self._json(HTTPStatus.CREATED, {"rtl_version": version.to_dict()})
                    return
                if path.startswith("/api/m1/specs/") and path.endswith("/rtl"):
                    spec_id = path.removeprefix("/api/m1/specs/").removesuffix("/rtl")
                    self._owned_spec(spec_id)
                    self._create_rtl(spec_id, payload)
                    return
                if path.startswith("/api/m1/rtl/") and path.endswith("/verify"):
                    version_id = path.removeprefix("/api/m1/rtl/").removesuffix("/verify")
                    self._owned_version(version_id)
                    run_id = service.submit_verification(version_id, v2_client)
                    self._json(HTTPStatus.ACCEPTED, {"run_id": run_id, "state": "submitted"})
                    return
                if path.startswith("/api/m1/rtl/") and path.endswith("/simulate"):
                    version_id = path.removeprefix("/api/m1/rtl/").removesuffix("/simulate")
                    self._owned_version(version_id)
                    run_id = service.submit_simulation(version_id, v2_client)
                    self._json(HTTPStatus.ACCEPTED, {"run_id": run_id, "state": "submitted"})
                    return
                if path.startswith("/api/m1/rtl/") and path.endswith("/gds"):
                    version_id = path.removeprefix("/api/m1/rtl/").removesuffix("/gds")
                    self._owned_version(version_id)
                    pdk = payload.get("pdk")
                    if not isinstance(pdk, str):
                        raise ValueError("pdk is required")
                    run_id = service.submit_rtl_to_gds(version_id, pdk, v2_client)
                    self._json(HTTPStatus.ACCEPTED, {"run_id": run_id, "state": "submitted", "pdk": pdk})
                    return
                self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "resource not found")
            except (AuthorizationError, PermissionError, KeyError, ValueError,
                    V2Unavailable, V2ClientError) as exc:
                self._handle_error(exc)

        def _health(self) -> dict[str, Any]:
            try:
                health = v2_client.health()
                session = v2_client.session()
            except V2Unavailable as exc:
                return {"app": "m1_rtl_to_gds", "status": "unavailable", "identity": None,
                        "reason": str(exc)}
            return {
                "app": "m1_rtl_to_gds",
                "status": "ok" if health.get("ok", health.get("status") == "ok") else "unavailable",
                "identity": (session.get("user") or {}).get("id") if isinstance(session, dict) else None,
                "v2": health,
            }

        def _create_spec(self, payload: dict[str, Any]) -> None:
            owner_id = self._owner_id()
            if "owner_id" in payload:
                raise ValueError("owner_id is derived from the v2 identity")
            raw_spec = payload.get("spec")
            description = payload.get("description")
            if raw_spec is not None and description is not None:
                raise ValueError("spec and description are exclusive")
            if description is not None:
                if not isinstance(description, str) or not description.strip():
                    raise ValueError("description must be non-empty text")
                assessment = provider.assess(description)
                state = assessment.get("status")
                if state == "needs_clarification":
                    questions = tuple(assessment.get("questions") or ())
                    session = service.assess_spec(owner_id, clarification_questions=questions)
                    self._json(HTTPStatus.CREATED, {"session": session.to_dict()})
                    return
                if state == "unsupported_scope":
                    reason = assessment.get("reason")
                    if not isinstance(reason, str) or not reason.strip():
                        raise ValueError("unsupported_scope requires a reason")
                    session = service.assess_spec(owner_id, unsupported_reason=reason)
                    self._json(HTTPStatus.CREATED, {"session": session.to_dict()})
                    return
                if state != "specified" or not isinstance(assessment.get("spec"), dict):
                    raise ValueError("Codex assessment did not return a SpecIR")
                raw_spec = assessment["spec"]
            spec = SpecIR.from_dict(raw_spec) if isinstance(raw_spec, dict) else None
            questions = tuple(payload.get("clarification_questions", ()))
            if not all(isinstance(item, str) and item.strip() for item in questions):
                raise ValueError("clarification_questions must contain non-empty text")
            unsupported = payload.get("unsupported_reason")
            if unsupported is not None and not isinstance(unsupported, str):
                raise ValueError("unsupported_reason must be text")
            session = service.assess_spec(
                owner_id, spec=spec, clarification_questions=questions,
                unsupported_reason=unsupported,
            )
            self._json(HTTPStatus.CREATED, {"session": session.to_dict()})

        def _register_teaching_package(self, session: Any) -> None:
            if session.spec is None or session.state.value != "frozen":
                return
            if session.spec.top == "counter":
                oracle = """module counter_tb;
reg clk = 0;
reg rst_n = 0;
reg enable = 0;
wire [7:0] q;
counter dut(.clk(clk), .rst_n(rst_n), .enable(enable), .q(q));
always #1 clk = ~clk;
initial begin
  #2 rst_n = 1; enable = 1;
  #2 if (q !== 8'h01) $fatal(1, \"counter mismatch\");
  $display(\"TB_SUMMARY total=1 errors=0\");
  $display(\"PASS\");
  $finish;
end
endmodule
"""
                oracle_ref = self._upload_oracle(oracle)
                service.register_verification_package(
                    session.spec_id,
                    VerificationPackage(
                        verification_id="counter-v1",
                        spec_id=session.spec_id,
                        compile_checks=("verilator-lint", "yosys-check"),
                        simulation_oracle_refs=(f"source:{oracle_ref}",),
                        simulation_top="counter_tb",
                    ),
                )
            elif session.spec.top == "sequence_detector":
                oracle = """module sequence_detector_tb;
reg clk = 0;
reg rst_n = 0;
reg din = 0;
wire hit;
sequence_detector dut(.clk(clk), .rst_n(rst_n), .din(din), .hit(hit));
always #1 clk = ~clk;
task tick(input bit value);
begin din = value; #2; end
endtask
initial begin
  #2 rst_n = 1;
  tick(1); tick(0); tick(1);
  if (!hit) $fatal(1, \"sequence mismatch\");
  $display(\"TB_SUMMARY total=1 errors=0\");
  $display(\"PASS\");
  $finish;
end
endmodule
"""
                oracle_ref = self._upload_oracle(oracle)
                service.register_verification_package(
                    session.spec_id,
                    VerificationPackage(
                        verification_id="sequence-detector-v1",
                        spec_id=session.spec_id,
                        compile_checks=("verilator-lint", "yosys-check"),
                        simulation_oracle_refs=(f"source:{oracle_ref}",),
                        simulation_top="sequence_detector_tb",
                    ),
                )

        def _upload_oracle(self, source: str) -> str:
            record = v2_client.upload_rtl(source)
            return record["input_id"]

        def _create_rtl(self, spec_id: str, payload: dict[str, Any]) -> None:
            source = payload.get("rtl_source")
            generator = payload.get("generator")
            if not isinstance(source, str) or not source.strip():
                raise ValueError("rtl_source must be non-empty text")
            if not isinstance(generator, str) or not generator.strip():
                raise ValueError("generator must be non-empty text")
            parent = payload.get("parent_version_id")
            if parent is not None and not isinstance(parent, str):
                raise ValueError("parent_version_id must be text")
            version = service.create_rtl_version_from_v2(
                spec_id, source, generator, v2_client, parent_version_id=parent,
            )
            self._json(HTTPStatus.CREATED, {"rtl_version": version.to_dict()})

        def _owned_spec(self, spec_id: str) -> None:
            session = service.get_session(spec_id)
            if session.owner_id != self._owner_id():
                raise AuthorizationError("spec belongs to another v2 identity")

        def _owned_version(self, version_id: str) -> None:
            version = service.get_rtl_version(version_id)
            self._owned_spec(version.spec_id)

        def _owner_id(self) -> str:
            session = v2_client.session()
            user = session.get("user") if isinstance(session, dict) else None
            owner_id = user.get("id") if isinstance(user, dict) else None
            if not isinstance(owner_id, str) or not owner_id:
                raise PermissionError("v2 identity is required")
            return owner_id

        def _body(self) -> dict[str, Any]:
            content_length = self.headers.get("Content-Length")
            if content_length is None:
                raise ValueError("Content-Length is required")
            try:
                length = int(content_length)
            except ValueError as exc:
                raise ValueError("Content-Length must be an integer") from exc
            if length < 0 or length > MAX_BODY_BYTES:
                raise ValueError("request body is too large")
            raw = self.rfile.read(length)
            try:
                value = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("request body must be JSON") from exc
            if not isinstance(value, dict):
                raise ValueError("request body must be a JSON object")
            return value

        def _handle_error(self, exc: Exception) -> None:
            if isinstance(exc, AuthorizationError):
                self._error(HTTPStatus.FORBIDDEN, "FORBIDDEN", str(exc))
            elif isinstance(exc, PermissionError):
                self._error(HTTPStatus.UNAUTHORIZED, "UNAUTHENTICATED", str(exc))
            elif isinstance(exc, KeyError):
                self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", str(exc))
            elif isinstance(exc, ValueError):
                self._error(HTTPStatus.UNPROCESSABLE_ENTITY, "VALIDATION_ERROR", str(exc))
            elif isinstance(exc, V2Unavailable):
                self._error(HTTPStatus.BAD_GATEWAY, "V2_UNAVAILABLE", str(exc))
            elif isinstance(exc, V2ClientError):
                self._error(HTTPStatus.BAD_GATEWAY, "V2_ERROR", str(exc))
            else:
                self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "M1 request failed")

        def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _error(self, status: HTTPStatus, code: str, message: str) -> None:
            self._json(status, {"error": {"code": code, "message": message}})

        def _file(self, path: Path, content_type: str) -> None:
            if not path.is_file():
                self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "resource not found")
                return
            raw = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer((host, port), M1Handler)
    return server
