from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from .service import M3Service


def build_server(host: str, port: int, service: M3Service) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            try:
                active = self._service()
                owner = self._owner(active)
                path = urlsplit(self.path).path
                if path == "/api/m3/comparisons":
                    self._json(200, {"comparisons": active.store.list(owner)})
                    return
                if path.startswith("/api/m3/comparisons/"):
                    self._json(200, {"comparison": active.get(path.rsplit("/", 1)[1], owner)})
                    return
                self._json(404, {"error": {"code": "NOT_FOUND", "message": "resource not found"}})
            except (KeyError, PermissionError) as exc:
                self._json(404 if isinstance(exc, KeyError) else 403, {"error": {"code": "REQUEST_FAILED", "message": str(exc)}})

        def do_POST(self) -> None:  # noqa: N802
            try:
                active = self._service()
                owner = self._owner(active)
                path = urlsplit(self.path).path
                payload = self._body()
                if path == "/api/m3/comparisons":
                    self._json(201, {"comparison": active.create(owner, payload)})
                    return
                prefix = "/api/m3/comparisons/"
                if path.startswith(prefix) and path.endswith("/run"):
                    self._json(202, {"comparison": active.run(path[len(prefix):-4].rstrip("/"), owner)})
                    return
                self._json(404, {"error": {"code": "NOT_FOUND", "message": "resource not found"}})
            except (KeyError, PermissionError, ValueError) as exc:
                self._json(422, {"error": {"code": "REQUEST_FAILED", "message": str(exc)}})

        def _service(self) -> M3Service:
            header = self.headers.get("Authorization", "")
            token = header[7:].strip() if header.lower().startswith("bearer ") else None
            return M3Service(service.store, service.v2.with_token(token))

        def _owner(self, active: M3Service) -> str:
            return active.v2.session()["user"]["id"]

        def _body(self) -> dict:
            value = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if not isinstance(value, dict):
                raise ValueError("request body must be an object")
            return value

        def _json(self, status: int, value: dict) -> None:
            raw = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *_args: object) -> None:
            return

    return ThreadingHTTPServer((host, port), Handler)
