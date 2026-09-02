"""Durable S4 plans and parameter-proposal reservations.

Runtime remains the authority for execution.  This store only makes the
orchestrator's intent, exact submitted typed call, and proposal consumption
recoverable across a scheduler restart.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path


class L1LoopStore:
    def __init__(self, database: str | Path) -> None:
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database) as c:
            c.execute("CREATE TABLE IF NOT EXISTS l1_loop_plan (plan_id TEXT PRIMARY KEY, trace_id TEXT NOT NULL, goal_id TEXT NOT NULL, state_id TEXT NOT NULL, call_json TEXT NOT NULL, status TEXT NOT NULL, receipt_json TEXT, run_id TEXT, proposal_id TEXT, patch_sha256 TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS l1_parameter_proposal (proposal_id TEXT PRIMARY KEY, trace_id TEXT NOT NULL, goal_id TEXT NOT NULL, state_id TEXT NOT NULL, patch_json TEXT NOT NULL, consumed_by TEXT)")
            plan_columns = {row[1] for row in c.execute("PRAGMA table_info(l1_loop_plan)")}
            if "submitted_call_sha256" not in plan_columns:
                c.execute("ALTER TABLE l1_loop_plan ADD COLUMN submitted_call_sha256 TEXT")
            proposal_columns = {row[1] for row in c.execute("PRAGMA table_info(l1_parameter_proposal)")}
            if "reservation_plan_id" not in proposal_columns:
                c.execute("ALTER TABLE l1_parameter_proposal ADD COLUMN reservation_plan_id TEXT")

    @staticmethod
    def _json(value: dict) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    def propose(self, plan_id: str, trace_id: str, goal_id: str, state_id: str, call: dict) -> None:
        with sqlite3.connect(self.database) as c:
            c.execute("INSERT INTO l1_loop_plan(plan_id,trace_id,goal_id,state_id,call_json,status,receipt_json,run_id) VALUES(?,?,?,?,?,?,?,?)", (plan_id, trace_id, goal_id, state_id, self._json(call), "proposed", None, None))

    def get(self, plan_id: str) -> dict:
        with sqlite3.connect(self.database) as c:
            row = c.execute("SELECT plan_id,trace_id,goal_id,state_id,call_json,status,receipt_json,run_id,proposal_id,patch_sha256,submitted_call_sha256 FROM l1_loop_plan WHERE plan_id=?", (plan_id,)).fetchone()
        if row is None:
            raise KeyError(plan_id)
        return {"plan_id": row[0], "trace_id": row[1], "goal_id": row[2], "state_id": row[3], "call": json.loads(row[4]), "status": row[5], "receipt": json.loads(row[6]) if row[6] else None, "run_id": row[7], "proposal_id": row[8], "patch_sha256": row[9], "submitted_call_sha256": row[10]}

    def reserve_proposal(self, proposal_id: str, trace_id: str, goal_id: str, state_id: str, plan_id: str) -> dict:
        """Reserve, but do not consume, a proposal for one durable plan."""
        with sqlite3.connect(self.database) as c:
            row = c.execute("SELECT trace_id,goal_id,state_id,patch_json,consumed_by,reservation_plan_id FROM l1_parameter_proposal WHERE proposal_id=?", (proposal_id,)).fetchone()
            plan = c.execute("SELECT trace_id,goal_id,state_id,status FROM l1_loop_plan WHERE plan_id=?", (plan_id,)).fetchone()
            if row is None or plan != (trace_id, goal_id, state_id, "proposed") or row[:3] != (trace_id, goal_id, state_id):
                raise ValueError("proposal is unavailable for this trace/goal/state")
            if row[4] is not None or row[5] not in {None, plan_id}:
                raise ValueError("proposal is unavailable for this trace/goal/state")
            changed = c.execute("UPDATE l1_parameter_proposal SET reservation_plan_id=? WHERE proposal_id=? AND consumed_by IS NULL AND (reservation_plan_id IS NULL OR reservation_plan_id=?)", (plan_id, proposal_id, plan_id)).rowcount
            if changed != 1:
                raise ValueError("proposal reservation raced")
            patch_sha256 = hashlib.sha256(row[3].encode()).hexdigest()
            c.execute("UPDATE l1_loop_plan SET proposal_id=?,patch_sha256=? WHERE plan_id=?", (proposal_id, patch_sha256, plan_id))
        return json.loads(row[3])

    def prepare_execution(self, plan_id: str, call: dict) -> None:
        """Atomically persist the exact canonical call before Runtime submission."""
        encoded = self._json(call)
        with sqlite3.connect(self.database) as c:
            changed = c.execute("UPDATE l1_loop_plan SET call_json=?,submitted_call_sha256=?,status='prepared' WHERE plan_id=? AND status='proposed'", (encoded, hashlib.sha256(encoded.encode()).hexdigest(), plan_id)).rowcount
        if changed != 1:
            raise ValueError("plan is not available for execution preparation")

    def release_reservation(self, plan_id: str) -> None:
        """Release only an unsubmitted plan after a pre-submit failure."""
        with sqlite3.connect(self.database) as c:
            plan = c.execute("SELECT proposal_id,status FROM l1_loop_plan WHERE plan_id=?", (plan_id,)).fetchone()
            if plan is None or plan[1] not in {"proposed", "prepared"}:
                return
            if plan[0]:
                c.execute("UPDATE l1_parameter_proposal SET reservation_plan_id=NULL WHERE proposal_id=? AND reservation_plan_id=? AND consumed_by IS NULL", (plan[0], plan_id))
            c.execute("UPDATE l1_loop_plan SET status='abandoned' WHERE plan_id=? AND status IN ('proposed','prepared')", (plan_id,))

    def record_receipt(self, plan_id: str, receipt: dict) -> None:
        """Commit receipt and proposal consumption in the same SQLite transaction."""
        with sqlite3.connect(self.database) as c:
            plan = c.execute("SELECT status,proposal_id FROM l1_loop_plan WHERE plan_id=?", (plan_id,)).fetchone()
            if plan is None or plan[0] != "prepared":
                raise ValueError("plan is not prepared or does not exist")
            if plan[1]:
                changed = c.execute("UPDATE l1_parameter_proposal SET consumed_by=?,reservation_plan_id=NULL WHERE proposal_id=? AND reservation_plan_id=? AND consumed_by IS NULL", (plan_id, plan[1], plan_id)).rowcount
                if changed != 1:
                    raise ValueError("proposal reservation is not owned by plan")
            changed = c.execute("UPDATE l1_loop_plan SET status=?,receipt_json=?,run_id=? WHERE plan_id=? AND status='prepared'", ("submitted", self._json(receipt), receipt.get("result", {}).get("run_id"), plan_id)).rowcount
            if changed != 1:
                raise ValueError("plan receipt commit raced")

    def save_proposal(self, proposal_id: str, trace_id: str, goal_id: str, state_id: str, patch: dict) -> None:
        with sqlite3.connect(self.database) as c:
            c.execute("INSERT INTO l1_parameter_proposal(proposal_id,trace_id,goal_id,state_id,patch_json,consumed_by,reservation_plan_id) VALUES(?,?,?,?,?,?,?)", (proposal_id, trace_id, goal_id, state_id, self._json(patch), None, None))
