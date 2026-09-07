"""Tiny SQLite checkpoint for resumability."""
import sqlite3
import time
from pathlib import Path
from typing import Optional


class Checkpoint:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS workers ("
            "  worker_key TEXT PRIMARY KEY,"
            "  status TEXT NOT NULL,"
            "  updated_at INTEGER NOT NULL,"
            "  error TEXT"
            ")"
        )
        self.conn.commit()

    def get_status(self, key: str) -> Optional[str]:
        row = self.conn.execute("SELECT status FROM workers WHERE worker_key=?", (key,)).fetchone()
        return row[0] if row else None

    def mark(self, key: str, status: str, error: str = "") -> None:
        self.conn.execute(
            "INSERT INTO workers(worker_key,status,updated_at,error) VALUES(?,?,?,?) "
            "ON CONFLICT(worker_key) DO UPDATE SET status=excluded.status,"
            " updated_at=excluded.updated_at, error=excluded.error",
            (key, status, int(time.time()), error),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
