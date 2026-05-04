from __future__ import annotations

import contextlib
import os
import sqlite3
from typing import Iterable


def ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)


def connect(db_path: str) -> sqlite3.Connection:
    ensure_parent_dir(db_path)

    conn = sqlite3.connect(db_path, timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS reservations (
          reservation_id TEXT PRIMARY KEY,
          run_key TEXT NOT NULL UNIQUE,
          command_json TEXT NOT NULL,
          reservation_status TEXT NOT NULL,
          job_id TEXT,
          not_before INTEGER,
          expires_at INTEGER,
          metadata_json TEXT,
          orchesjob_start_options_json TEXT NOT NULL DEFAULT '[]',
          created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL,
          dispatched_at INTEGER,
          last_error TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_reservations_status_not_before
          ON reservations (reservation_status, not_before);

        CREATE INDEX IF NOT EXISTS idx_reservations_job_id
          ON reservations (job_id);

        CREATE INDEX IF NOT EXISTS idx_reservations_updated_at
          ON reservations (updated_at);
        """
    )


@contextlib.contextmanager
def transaction(conn: sqlite3.Connection) -> Iterable[None]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
