from __future__ import annotations

import time
import uuid
from typing import Any

from .store import M3Store


class M3Service:
    def __init__(self, store: M3Store, v2: Any) -> None:
        self.store = store
        self.v2 = v2

    @classmethod
    def in_memory(cls, v2: Any) -> "M3Service":
        return cls(M3Store(), v2)

    def create(self, owner_id: str, payload: dict) -> dict:
        for key in ("rtl_input_id", "pdk", "sdc", "evaluator", "search_space", "budget", "stop_condition"):
            if key not in payload:
                raise ValueError(key + " is required")
        record = {
            "comparison_id": "m3-" + uuid.uuid4().hex,
            "owner_id": owner_id,
            "rtl_input_id": payload["rtl_input_id"],
            "pdk": payload["pdk"],
            "sdc": payload["sdc"],
            "toolchain": payload.get("toolchain", {}),
            "evaluator": payload["evaluator"],
            "search_space": payload["search_space"],
            "budget": payload["budget"],
            "stop_condition": payload["stop_condition"],
            "state": "created",
            "strategies": {"baseline": self._strategy("baseline"), "orfs_agent": self._strategy("orfs_agent")},
        }
        self.store.put(record["comparison_id"], record)
        return record

    @staticmethod
    def _strategy(name: str) -> dict:
        return {"strategy": name, "status": "not_started", "observations": [], "trajectory": [], "run_ids": [], "failures": [], "cost": {}}

    def run(self, comparison_id: str, owner_id: str) -> dict:
        record = self.get(comparison_id, owner_id)
        record["state"] = "running"
        for name in ("baseline", "orfs_agent"):
            strategy = record["strategies"][name]
            started = time.monotonic()
            task = record.get("tasks", {}).get(name)
            if not task:
                strategy["status"] = "blocked"
                strategy["failures"].append({"stage": "admission", "reason": name + " task protocol is not registered"})
            else:
                strategy["run_ids"].append(self.v2.submit(task, "m3-" + name + "-" + comparison_id))
                strategy["status"] = "submitted"
                strategy["observations"].append({"status": "submitted", "strategy": name})
                strategy["trajectory"].append({"step": 0, "qor": None, "status": "submitted"})
            strategy["cost"]["submission_seconds"] = round(time.monotonic() - started, 6)
        record["state"] = "completed"
        self.store.put(comparison_id, record)
        return record

    def get(self, comparison_id: str, owner_id: str) -> dict:
        record = self.store.get(comparison_id)
        if record["owner_id"] != owner_id:
            raise PermissionError("comparison belongs to another identity")
        return record
