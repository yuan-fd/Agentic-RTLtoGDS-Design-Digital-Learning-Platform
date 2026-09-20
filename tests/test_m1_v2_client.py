from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

M1_SRC = Path(__file__).parents[1] / "apps/m1_rtl_to_gds/src"
if str(M1_SRC) not in sys.path:
    sys.path.insert(0, str(M1_SRC))

from openroad_app_m1.v2_client import (
    V2Client,
    V2ClientError,
    V2Unavailable,
)


class Response:
    def __init__(self, payload: object) -> None:
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


def test_v2_client_uses_kernel_http_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, bytes | None]] = []
    replies = iter((
        {"ok": True},
        {"session": {"user": {"id": "user-1", "username": "student", "role": "member"}}},
        {"input": {"input_id": "input-1"}},
        {"run": {"run_id": "run-1", "status": "queued"}},
    ))

    def open_url(request: object, timeout: float) -> Response:
        calls.append((request.method, request.full_url, request.data))  # type: ignore[attr-defined]
        assert timeout == 3.0
        assert request.headers.get("Authorization") == "Bearer token-1"  # type: ignore[attr-defined]
        return Response(next(replies))

    monkeypatch.setattr("urllib.request.urlopen", open_url)
    client = V2Client("http://v2.test/", token="token-1", timeout=3.0)

    assert client.health() == {"ok": True}
    assert client.session() == {"user": {"id": "user-1", "username": "student", "role": "member"}}
    assert client.upload_rtl("module top; endmodule") == {"input_id": "input-1"}
    assert client.submit({"task_id": "task-1"}, idempotency_key="m1:task-1")["run"]["run_id"] == "run-1"
    assert calls[2][0] == "POST"
    assert calls[2][2] == b"module top; endmodule"
    assert "idempotency_key=m1%3Atask-1" in calls[3][1]


def test_v2_client_exposes_http_failures_and_unavailability(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(*_args: object, **_kwargs: object) -> None:
        raise OSError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", unavailable)
    with pytest.raises(V2Unavailable, match="unreachable"):
        V2Client("http://v2.test").health()


def test_v2_client_rejects_non_http_base_url() -> None:
    with pytest.raises(ValueError, match="http or https"):
        V2Client("file:///tmp/v2")


def test_v2_client_rejects_malformed_plugin_catalogue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: Response({"plugins": {}}))

    with pytest.raises(V2ClientError, match="plugin catalogue"):
        V2Client("http://v2.test").plugins()
