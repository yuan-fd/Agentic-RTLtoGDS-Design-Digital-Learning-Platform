"""One-shot durable consumption records for authorized L1→L2 handoffs."""
from __future__ import annotations
import sqlite3
from pathlib import Path

class L2HandoffStore:
    def __init__(self, database: str | Path) -> None:
        self.database=Path(database); self.database.parent.mkdir(parents=True,exist_ok=True)
        with self._connect() as c:
            c.execute("CREATE TABLE IF NOT EXISTS l2_handoff_consumption(authorization_id TEXT PRIMARY KEY, run_id TEXT)")
    def _connect(self):
        c=sqlite3.connect(self.database); c.row_factory=sqlite3.Row; return c
    def claim(self, authorization_id: str) -> str | None:
        with self._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row=c.execute("SELECT run_id FROM l2_handoff_consumption WHERE authorization_id=?",(authorization_id,)).fetchone()
            if row is not None:
                c.commit(); return row["run_id"] or ""
            c.execute("INSERT INTO l2_handoff_consumption VALUES(?,NULL)",(authorization_id,)); c.commit(); return None
    def bind(self, authorization_id: str, run_id: str) -> None:
        with self._connect() as c:
            changed=c.execute("UPDATE l2_handoff_consumption SET run_id=? WHERE authorization_id=? AND run_id IS NULL",(run_id,authorization_id))
            if changed.rowcount != 1: raise ValueError("L2 authorization consumption binding conflict")
    def release(self, authorization_id: str) -> None:
        with self._connect() as c: c.execute("DELETE FROM l2_handoff_consumption WHERE authorization_id=? AND run_id IS NULL",(authorization_id,))
