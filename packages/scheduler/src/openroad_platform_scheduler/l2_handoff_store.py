"""One-shot durable consumption records for authorized L1→L2 handoffs."""
from __future__ import annotations
import sqlite3
from pathlib import Path

class L2HandoffStore:
    def __init__(self, database: str | Path) -> None:
        self.database=Path(database); self.database.parent.mkdir(parents=True,exist_ok=True)
        with self._connect() as c:
            c.execute("CREATE TABLE IF NOT EXISTS l2_handoff_consumption(authorization_id TEXT PRIMARY KEY, run_id TEXT, target_kind TEXT)")
            columns={row[1] for row in c.execute("PRAGMA table_info(l2_handoff_consumption)")}
            if "target_kind" not in columns:
                c.execute("ALTER TABLE l2_handoff_consumption ADD COLUMN target_kind TEXT")
    def _connect(self):
        c=sqlite3.connect(self.database); c.row_factory=sqlite3.Row; return c
    def claim(self, authorization_id: str) -> str | None:
        target = self.claim_target(authorization_id)
        return None if target is None else target[1]
    def claim_target(self, authorization_id: str) -> tuple[str, str] | None:
        with self._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row=c.execute("SELECT run_id,target_kind FROM l2_handoff_consumption WHERE authorization_id=?",(authorization_id,)).fetchone()
            if row is not None:
                c.commit(); return (str(row["target_kind"] or ""), str(row["run_id"] or ""))
            c.execute("INSERT INTO l2_handoff_consumption(authorization_id,run_id,target_kind) VALUES(?,NULL,NULL)",(authorization_id,)); c.commit(); return None
    def bind(self, authorization_id: str, run_id: str) -> None:
        self.bind_target(authorization_id, "runtime_run", run_id)
    def bind_target(self, authorization_id: str, target_kind: str, target_id: str) -> None:
        if not target_kind or not target_id:
            raise ValueError("L2 handoff target kind and id are required")
        with self._connect() as c:
            changed=c.execute("UPDATE l2_handoff_consumption SET run_id=?,target_kind=? WHERE authorization_id=? AND run_id IS NULL",(target_id,target_kind,authorization_id))
            if changed.rowcount == 1:
                return
            row=c.execute("SELECT run_id,target_kind FROM l2_handoff_consumption WHERE authorization_id=?",(authorization_id,)).fetchone()
            if row is None or row["run_id"] != target_id or row["target_kind"] != target_kind:
                raise ValueError("L2 authorization consumption binding conflict")
    def release(self, authorization_id: str) -> None:
        with self._connect() as c: c.execute("DELETE FROM l2_handoff_consumption WHERE authorization_id=? AND run_id IS NULL",(authorization_id,))
