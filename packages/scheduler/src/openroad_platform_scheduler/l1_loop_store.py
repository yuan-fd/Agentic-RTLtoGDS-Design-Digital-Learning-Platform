"""Durable S4 plan records; execution facts remain in Runtime and S2 trace."""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path


class L1LoopStore:
    def __init__(self, database: str | Path) -> None:
        self.database = Path(database); self.database.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database) as c:
            c.execute("CREATE TABLE IF NOT EXISTS l1_loop_plan (plan_id TEXT PRIMARY KEY, trace_id TEXT NOT NULL, goal_id TEXT NOT NULL, state_id TEXT NOT NULL, call_json TEXT NOT NULL, status TEXT NOT NULL, receipt_json TEXT, run_id TEXT)")
    def propose(self, plan_id: str, trace_id: str, goal_id: str, state_id: str, call: dict) -> None:
        with sqlite3.connect(self.database) as c: c.execute("INSERT INTO l1_loop_plan VALUES(?,?,?,?,?,?,?,?)", (plan_id, trace_id, goal_id, state_id, json.dumps(call, sort_keys=True), "proposed", None, None))
    def get(self, plan_id: str) -> dict:
        with sqlite3.connect(self.database) as c: row = c.execute("SELECT * FROM l1_loop_plan WHERE plan_id=?", (plan_id,)).fetchone()
        if row is None: raise KeyError(plan_id)
        return {"plan_id": row[0], "trace_id": row[1], "goal_id": row[2], "state_id": row[3], "call": json.loads(row[4]), "status": row[5], "receipt": json.loads(row[6]) if row[6] else None, "run_id": row[7]}
    def record_receipt(self, plan_id: str, receipt: dict) -> None:
        with sqlite3.connect(self.database) as c:
            changed = c.execute("UPDATE l1_loop_plan SET status=?,receipt_json=?,run_id=? WHERE plan_id=? AND status='proposed'", ("submitted", json.dumps(receipt, sort_keys=True), receipt.get("result", {}).get("run_id"), plan_id)).rowcount
        if changed != 1: raise ValueError("plan is not proposed or does not exist")
