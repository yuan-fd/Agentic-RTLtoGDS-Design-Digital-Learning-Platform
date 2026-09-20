from __future__ import annotations

import json
import urllib.error
import urllib.request


class V2Error(RuntimeError):
    pass


class V2Client:
    def __init__(self, base_url: str, token: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    def with_token(self, token: str | None) -> "V2Client":
        return V2Client(self.base_url, token)

    def session(self) -> dict:
        return self._call("GET", "/kernel/auth/session").get("session") or {}

    def upload(self, source: str) -> str:
        headers = {"Accept": "application/json", "Content-Type": "application/octet-stream"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        request = urllib.request.Request(self.base_url + "/kernel/inputs", data=source.encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read())["input"]["input_id"]
        except (urllib.error.URLError, urllib.error.HTTPError, KeyError, json.JSONDecodeError) as exc:
            raise V2Error(str(exc)) from exc

    def submit(self, task: dict, key: str) -> str:
        reply = self._call("POST", "/kernel/runs?idempotency_key=" + key, {"task": task})
        return reply["run"]["run_id"]

    def _call(self, method: str, path: str, payload: dict | None = None) -> dict:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        body = None if payload is None else json.dumps(payload).encode()
        if body is not None:
            headers["Content-Type"] = "application/json"
        try:
            with urllib.request.urlopen(urllib.request.Request(self.base_url + path, data=body, headers=headers, method=method), timeout=30) as response:
                return json.loads(response.read())
        except (urllib.error.URLError, urllib.error.HTTPError, KeyError, json.JSONDecodeError) as exc:
            raise V2Error(str(exc)) from exc
