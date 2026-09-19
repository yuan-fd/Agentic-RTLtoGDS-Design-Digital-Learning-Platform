"""Independent Direct LLM candidate source for M1."""

from __future__ import annotations

from typing import Any, Protocol

from .models import RTLVersion
from .service import M1Service


class DirectLLMProvider(Protocol):
    def generate(self, payload: dict[str, Any]) -> object:
        """Return only the generated SystemVerilog source."""


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
        if any(marker in output for marker in (
            "#!", "$((", "$(", "os.system", "subprocess", "rm -rf", "python -c", "import os",
        )):
            raise ValueError("Direct LLM provider returned non-RTL command text")
        return self.service.create_rtl_version_from_v2(
            spec_id, output, "direct_llm", v2_client
        )
