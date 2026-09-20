from __future__ import annotations

import time
import uuid
from typing import Any

from .store import M2Store


class M2Service:
    def __init__(self, store: M2Store, v2: Any) -> None:
        self.store = store
        self.v2 = v2

    @classmethod
    def in_memory(cls, v2: Any) -> "M2Service":
        return cls(M2Store(), v2)

    def create(self, owner_id: str, payload: dict) -> dict:
        required = ("spec_id", "verification_id", "pdk")
        if any(not isinstance(payload.get(key), str) or not payload[key].strip() for key in required):
            raise ValueError("spec_id, verification_id, and pdk are required")
        result = {
            "comparison_id": "m2-" + uuid.uuid4().hex,
            "owner_id": owner_id,
            "spec_id": payload["spec_id"],
            "verification_id": payload["verification_id"],
            "pdk": payload["pdk"],
            "state": "created",
            "candidates": {
                "direct_llm": self._candidate("direct_llm"),
                "rtlscout": self._candidate("rtlscout"),
            },
        }
        self.store.put(result["comparison_id"], result)
        return result

    @staticmethod
    def _candidate(generator: str) -> dict:
        return {"generator": generator, "status": "not_started", "run_ids": [], "artifacts": [], "qor": [], "failure_stage": None, "duration_seconds": None}

    def run(self, comparison_id: str, owner_id: str) -> dict:
        record = self.get(comparison_id, owner_id)
        record["state"] = "running"
        for generator in ("direct_llm", "rtlscout"):
            candidate = record["candidates"][generator]
            started = time.monotonic()
            source = record.get("candidate_sources", {}).get(generator)
            if not source:
                candidate["status"] = "toolchain_unavailable"
                candidate["failure_stage"] = "generation"
                candidate["failure_reason"] = generator + " candidate source is not registered"
            else:
                input_record = self.v2.upload_rtl(source)
                task = {"schema_version": 3, "task_id": "m2-" + generator + "-" + comparison_id, "project_id": "teaching-m2", "design_id": comparison_id + "-" + generator, "plugin_id": "orfs", "inputs": {"spec_id": record["spec_id"], "verification_id": record["verification_id"], "platform": record["pdk"], "candidate_generator": generator}, "staged_inputs": [{"destination": "inputs/design.sv", "input_id": input_record["input_id"], "required": True}], "expected_artifacts": ["gds", "def", "odb", "netlist", "report"], "timeout_seconds": 7200, "max_attempts": 1}
                candidate["run_ids"] = [self.v2.submit(task, task["task_id"])]
                candidate["status"] = "submitted"
            candidate["duration_seconds"] = round(time.monotonic() - started, 6)
        record["state"] = "completed"
        self.store.put(comparison_id, record)
        return record

    def get(self, comparison_id: str, owner_id: str) -> dict:
        record = self.store.get(comparison_id)
        if record["owner_id"] != owner_id:
            raise PermissionError("comparison belongs to another identity")
        return record
