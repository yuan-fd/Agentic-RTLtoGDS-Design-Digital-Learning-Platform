from apps.l1_workbench.terminal_dashboard import Dashboard


class Client:
    def __init__(self):
        self.calls = []

    def post(self, path, payload):
        self.calls.append((path, payload))
        if path.endswith("/m1-proposal"):
            return {"proposal_id": "proposal-1"}
        if path.endswith("/candidates"):
            return {"runtime": {"run": {"status": "succeeded"}}}
        if path.endswith("/m1-compare"):
            return {"decision": "stop", "decision_reason": "no_measured_improvement",
                    "area_baseline_ratio": 1.0}
        raise AssertionError(path)

    def get(self, path):
        return {"events": []}


def test_terminal_m1_commands_only_use_published_api_and_store_no_authoritative_result() -> None:
    client = Client()
    dashboard = Dashboard(client)
    dashboard.sid = "session-1"
    dashboard.command(":m1-propose")
    dashboard.command(":candidate proposal-1")
    dashboard.command(":compare baseline-run-1")
    assert [path for path, _ in client.calls] == [
        "/api/l1/sessions/session-1/m1-proposal",
        "/api/l1/sessions/session-1/candidates",
        "/api/l1/sessions/session-1/m1-compare",
    ]
    assert dashboard.events == []
    assert "M1 decision: stop" in dashboard.notice
