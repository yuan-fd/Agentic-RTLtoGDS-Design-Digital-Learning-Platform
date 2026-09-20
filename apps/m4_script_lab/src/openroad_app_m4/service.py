from __future__ import annotations

import uuid
from typing import Any

from .store import M4Store


REGISTERED_RECIPES = {"course-counter-nangate45-v1", "course-sequence-fsm-nangate45-v1"}
ALLOWLIST = {recipe: {"flow.tcl", "config.py"} for recipe in REGISTERED_RECIPES}


class M4Service:
    def __init__(self, store: M4Store, v2: Any) -> None:
        self.store = store
        self.v2 = v2

    @classmethod
    def in_memory(cls, v2: Any) -> "M4Service":
        return cls(M4Store(), v2)

    def create(self, owner_id: str, payload: dict) -> dict:
        recipe_id = payload.get("recipe_id")
        touched = payload.get("touched_paths", [])
        if recipe_id not in REGISTERED_RECIPES:
            raise ValueError("recipe_id is not registered")
        if not isinstance(touched, list) or any(path not in ALLOWLIST[recipe_id] for path in touched):
            return self._save({"proposal_id": "m4-" + uuid.uuid4().hex, "owner_id": owner_id, "recipe_id": recipe_id, "state": "rejected", "reason": "patch touches a path outside the registered recipe allowlist", "touched_paths": touched, "diff": payload.get("diff", "")})
        if not isinstance(payload.get("diff"), str) or not payload["diff"].strip():
            raise ValueError("diff is required")
        return self._save({"proposal_id": "m4-" + uuid.uuid4().hex, "owner_id": owner_id, "recipe_id": recipe_id, "state": "proposed", "reason": None, "touched_paths": touched, "diff": payload["diff"], "run_id": None})

    def confirm(self, proposal_id: str, owner_id: str) -> dict:
        proposal = self.get(proposal_id, owner_id)
        if proposal["state"] != "proposed":
            raise ValueError("only an allowlisted proposed patch can be confirmed")
        proposal["state"] = "confirmed"
        return self._save(proposal)

    def run(self, proposal_id: str, owner_id: str) -> dict:
        proposal = self.get(proposal_id, owner_id)
        if proposal["state"] != "confirmed":
            raise ValueError("proposal must be confirmed before execution")
        input_id = self.v2.upload(proposal["diff"])
        task = {"schema_version": 3, "task_id": "m4-" + proposal_id, "project_id": "teaching-m4", "design_id": proposal["recipe_id"], "plugin_id": "orfs", "inputs": {"recipe_id": proposal["recipe_id"], "patch_path": proposal["touched_paths"], "isolated_workspace": True}, "staged_inputs": [{"destination": "proposal.patch", "input_id": input_id, "required": True}], "expected_artifacts": ["log", "report"], "timeout_seconds": 1800, "max_attempts": 1}
        proposal["run_id"] = self.v2.submit(task, task["task_id"])
        proposal["state"] = "submitted"
        return self._save(proposal)

    def get(self, proposal_id: str, owner_id: str) -> dict:
        proposal = self.store.get(proposal_id)
        if proposal["owner_id"] != owner_id:
            raise PermissionError("proposal belongs to another identity")
        return proposal

    def _save(self, value: dict) -> dict:
        self.store.put(value["proposal_id"], value)
        return value
