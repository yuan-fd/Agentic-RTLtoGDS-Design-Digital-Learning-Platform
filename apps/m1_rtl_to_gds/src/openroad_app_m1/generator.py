"""Independent Direct LLM candidate source for M1."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Protocol

from .models import RTLVersion
from .service import M1Service


class DirectLLMProvider(Protocol):
    def generate(self, payload: dict[str, Any]) -> object:
        """Return only the generated SystemVerilog source."""


class DirectLLMError(ValueError):
    """The fixed server-side Direct LLM command did not produce its result."""


class CodexCLIProvider:
    MODEL = "gpt-5.6-terra"

    def generate(self, payload: dict[str, Any]) -> str:
        return self._run(
            "Generate only synthesizable SystemVerilog source for this frozen SpecIR. "
            "Return no Markdown fences and no explanation.\n\n"
            + json.dumps(payload["spec"], ensure_ascii=False, sort_keys=True)
        )

    def assess(self, description: str) -> dict[str, Any]:
        raw = self._run(
            "Convert this digital-design description into the M1 SpecIR JSON contract. "
            "Return exactly one JSON object with status set to specified, "
            "needs_clarification, or unsupported_scope. For specified include a complete "
            "SpecIR object under spec. The SpecIR object has schema_version=1 and fields "
            "spec_id, design_id, top, functionality, objective, ports, clock, reset, "
            "constraints, and acceptance_criteria. Each port has name, direction, and "
            "width, and schema_version=1. Put clock_period_ns in constraints when a "
            "timing period is given. "
            "For needs_clarification include questions. "
            "Do not invent missing clock, reset, ports, timing, or acceptance behavior.\n\n"
            + description
        )
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise DirectLLMError("Codex assessment did not return a JSON object")
        return value

    def _run(self, prompt: str) -> str:
        with tempfile.TemporaryDirectory(prefix="m1-codex-") as directory:
            output = Path(directory) / "last-message.txt"
            command = [
                "codex", "exec", "--ephemeral", "--skip-git-repo-check",
                "--sandbox", "read-only", "--model", self.MODEL,
                "--output-last-message", str(output), prompt,
            ]
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
            if completed.returncode != 0:
                raise DirectLLMError(
                    f"Codex CLI failed with exit code {completed.returncode}: "
                    f"{completed.stderr.strip()}"
                )
            return output.read_text(encoding="utf-8")


class DirectLLMGenerator:
    def __init__(self, service: M1Service) -> None:
        self.service = service

    def generate(self, spec_id: str, provider: DirectLLMProvider, v2_client: Any) -> RTLVersion:
        session = self.service.get_session(spec_id)
        if session.state.value != "frozen" or session.spec is None:
            raise ValueError("Direct LLM generation requires a frozen spec")
        payload = {"spec_id": spec_id, "spec": session.spec.to_dict()}
        output = provider.generate(payload)
        if not isinstance(output, str) or not output.strip():
            raise ValueError("Direct LLM provider did not return RTL")
        return self.service.create_rtl_version_from_v2(
            spec_id, output, "direct_llm", v2_client
        )
