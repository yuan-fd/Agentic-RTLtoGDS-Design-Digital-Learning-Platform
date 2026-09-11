import json
import stat
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / ".external-src" / "rtlscout"


def _fake_codex(path: Path) -> Path:
    path.write_text(
        """#!/usr/bin/env python3
import json
import sys
from pathlib import Path

schema = Path(sys.argv[sys.argv.index('--output-schema') + 1])
output = Path(sys.argv[sys.argv.index('--output-last-message') + 1])
properties = json.loads(schema.read_text())['properties']
if 'tool_call' in properties:
    value = {'content': 'List the bounded workspace.', 'tool_call': {'name': 'ls', 'arguments': {}}}
else:
    value = {'content': 'Native RTLScout run summary.'}
output.write_text(json.dumps(value))
""",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_managed_provider_returns_upstream_chat_types_and_records_trace(tmp_path, monkeypatch):
    openai_stub = types.ModuleType("openai")
    openai_stub.OpenAI = object
    monkeypatch.setitem(sys.modules, "openai", openai_stub)
    sys.path.insert(0, str(UPSTREAM))
    try:
        from openroad_platform_execution.rtlscout_managed_provider import (
            ManagedCodexRTLScoutClient,
        )
        from core.llm_client import ChatResponse

        trace = tmp_path / "trace.json"
        client = ManagedCodexRTLScoutClient(
            model="gpt-5.6-terra",
            executable=_fake_codex(tmp_path / "codex"),
            trace_path=trace,
        )
        response = client.chat_completion(
            [{"role": "system", "content": "native agent"}],
            [{
                "type": "function",
                "function": {
                    "name": "ls",
                    "description": "list files",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            }],
        )

        assert isinstance(response, ChatResponse)
        assert response.tool_calls[0].name == "ls"
        assert json.loads(response.tool_calls[0].arguments) == {}
        evidence = json.loads(trace.read_text(encoding="utf-8"))
        assert evidence["native_agent_owner"] == "huawei-csl/rtlscout core.agent.RTLAgent"
        assert evidence["calls"][0]["tool_name"] == "ls"
        assert evidence["credential_source"].startswith("platform-managed Codex")
    finally:
        sys.path.remove(str(UPSTREAM))


def test_active_codex_path_invokes_native_entrypoint_instead_of_local_candidate_loop():
    adapter = (ROOT / "packages/execution/src/openroad_platform_execution/rtlscout_adapter.py").read_text()
    driver = (ROOT / "packages/execution/src/openroad_platform_execution/rtlscout_native_driver.py").read_text()

    active_branch = adapter.split('if provider == "codex-cli":', 1)[1].split("else:", 1)[0]
    assert "rtlscout_native_driver.py" in active_branch
    assert "_codex_cli_candidates(" not in active_branch
    assert "import run_benchmark as native_entrypoint" in driver
    assert "native_entrypoint.main()" in driver
    assert "native_runner.build_client = build_managed_client" in driver
