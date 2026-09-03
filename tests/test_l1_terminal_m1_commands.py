from apps.l1_workbench.terminal_dashboard import Dashboard, _safe_text


class Client:
    def __init__(self):
        self.calls = []

    def post(self, path, payload):
        self.calls.append((path, payload))
        if path.endswith("/m1-proposal"):
            return {"proposal_id": "proposal-1"}
        if path.endswith("/candidates"):
            return {"plan": {"run_id": "candidate-run-1"}}
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
    candidate_payload = client.calls[1][1]
    assert candidate_payload["wait"] is False


def test_terminal_baseline_returns_to_cursor_polling_without_waiting_for_runtime() -> None:
    class BaselineClient(Client):
        def post(self, path, payload):
            self.calls.append((path, payload))
            assert path.endswith("/execute")
            return {"plan": {"run_id": "baseline-run-1"}}

    client = BaselineClient()
    dashboard = Dashboard(client)
    dashboard.sid = "session-1"
    dashboard.command(":baseline")
    assert client.calls[0][1]["wait"] is False
    assert "polling durable cursor events" in dashboard.notice


def test_terminal_derives_m1_next_command_only_from_durable_events() -> None:
    dashboard = Dashboard(Client())
    dashboard.events = [{
        "kind": "goal_finalized", "facts": {"goal_ir": {}}, "sequence": 1,
    }, {
        "kind": "state_transition", "facts": {"run_id": "baseline-run"}, "sequence": 2,
    }, {
        "kind": "tool_called", "tool": "set_flow_params",
        "facts": {"call_id": "call-proposal"}, "sequence": 3,
    }]
    assert "Next: :candidate proposal-call-proposal" in "\n".join(dashboard._client_rows())


def test_terminal_teaching_projection_redacts_paths_commands_and_secrets() -> None:
    visible = _safe_text("token=abc /private/work $ openroad python3 secret: xyz")
    assert "abc" not in visible and "/private/work" not in visible and "openroad" not in visible
    assert "<redacted>" in visible and "<path-redacted>" in visible and "<command-redacted>" in visible
