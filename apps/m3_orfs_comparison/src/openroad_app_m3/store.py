from __future__ import annotations

import json
import sqlite3
import threading


class M3Store:
    def __init__(self, database: str = ":memory:") -> None:
        self.connection = sqlite3.connect(database, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.connection.execute("CREATE TABLE IF NOT EXISTS comparisons (comparison_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        self.connection.commit()

    def put(self, key: str, value: dict) -> None:
        with self.lock:
            self.connection.execute("INSERT OR REPLACE INTO comparisons VALUES (?, ?)", (key, json.dumps(value, sort_keys=True)))
            self.connection.commit()

    def get(self, key: str) -> dict:
        with self.lock:
            row = self.connection.execute("SELECT payload FROM comparisons WHERE comparison_id = ?", (key,)).fetchone()
        if row is None:
            raise KeyError(key)
        return json.loads(row["payload"])

    def list(self, owner_id: str) -> list[dict]:
        with self.lock:
            rows = self.connection.execute("SELECT payload FROM comparisons ORDER BY comparison_id").fetchall()
        values = [json.loads(row["payload"]) for row in rows]
        return [value for value in values if value["owner_id"] == owner_id]

    def close(self) -> None:
        self.connection.close()
