"""The only M1 door to the v2 execution foundation."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Any


class V2ClientError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, body: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


class V2Unavailable(V2ClientError):
    """The configured v2 service could not be reached."""


class V2Client:
    def __init__(self, base_url: str, *, token: str | None = None, timeout: float = 30.0) -> None:
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("v2 base_url must use http or https")
        if timeout <= 0:
            raise ValueError("v2 timeout must be positive")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def health(self) -> dict[str, Any]:
        return self._call("GET", "/kernel/health")

    def session(self) -> dict[str, Any] | None:
        payload = self._call("GET", "/kernel/auth/session")
        return payload.get("session")

    def plugins(self) -> list[dict[str, Any]]:
        payload = self._call("GET", "/kernel/plugins")
        plugins = payload.get("plugins")
        if not isinstance(plugins, list) or not all(isinstance(item, dict) for item in plugins):
            raise V2ClientError("v2 returned an invalid plugin catalogue", body=payload)
        return plugins

    def upload_rtl(self, rtl_source: str) -> dict[str, Any]:
        if not isinstance(rtl_source, str) or not rtl_source.strip():
            raise ValueError("RTL source must be non-empty text")
        reply = self._call(
            "POST", "/kernel/inputs", payload=rtl_source.encode("utf-8")
        )
        input_record = reply.get("input")
        if not isinstance(input_record, dict) or not input_record.get("input_id"):
            raise V2ClientError("v2 returned an input response without input_id", body=reply)
        return input_record

    def submit(self, task: Mapping[str, Any], *, idempotency_key: str) -> dict[str, Any]:
        if not isinstance(task, Mapping) or not idempotency_key.strip():
            raise ValueError("submit requires a task object and idempotency key")
        return self._call(
            "POST", "/kernel/runs", payload={"task": dict(task)},
            query={"idempotency_key": idempotency_key, "idempotent": "1"},
        )

    def run(self, run_id: str) -> dict[str, Any]:
        return self._call("GET", f"/kernel/runs/{_segment(run_id)}")

    def timeline(self, run_id: str) -> list[dict[str, Any]]:
        return self._call("GET", f"/kernel/runs/{_segment(run_id)}/timeline")["timeline"]

    def metrics(self, run_id: str) -> list[dict[str, Any]]:
        return self._call("GET", f"/kernel/runs/{_segment(run_id)}/metrics")["metrics"]

    def artifacts(self, run_id: str) -> list[dict[str, Any]]:
        return self._call("GET", f"/kernel/runs/{_segment(run_id)}/artifacts")["artifacts"]

    def _call(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, Any] | bytes | None = None,
        query: Mapping[str, str] | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        if query:
            url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v})
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        body: bytes | None = None
        if payload is not None:
            if isinstance(payload, bytes):
                body = payload
                headers["Content-Type"] = "application/octet-stream"
            else:
                body = json.dumps(dict(payload)).encode("utf-8")
                headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = _decode(exc.read())
            raise V2ClientError(
                f"v2 returned HTTP {exc.code}: {_error_text(detail)}",
                status=exc.code, body=detail,
            ) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise V2Unavailable(f"v2 at {self.base_url} is unreachable: {exc}") from exc
        if not raw:
            return None
        decoded = _decode(raw)
        if isinstance(decoded, (dict, list)):
            return decoded
        raise V2ClientError(f"v2 returned a non-JSON body for {method} {path}")


def _segment(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("v2 path identifier must be non-empty text")
    return urllib.parse.quote(value, safe="")


def _decode(raw: bytes) -> Any:
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return raw.decode("utf-8", errors="replace")[:1000]


def _error_text(detail: Any) -> str:
    if isinstance(detail, Mapping) and detail.get("error"):
        return str(detail["error"])
    return str(detail)
