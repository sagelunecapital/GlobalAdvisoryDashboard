"""
DB schema, table creation, and connection factory for the indicator database.

Table: indicators
  date           TEXT PRIMARY KEY  -- ISO-8601 YYYY-MM-DD
  spx_daily_high REAL NOT NULL     -- SPX daily HIGH (DEC-2026-04-18-01)
  spx_12d_ema    REAL NOT NULL     -- 12-day EMA of spx_daily_high
  spx_25d_ema    REAL NOT NULL     -- 25-day EMA of spx_daily_high
  mmth           REAL NOT NULL     -- % stocks above 200-day MA

WAL mode is enabled for ACID guarantees with concurrent readers.
"""

import sqlite3
from pathlib import Path


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS indicators (
    date           TEXT PRIMARY KEY,
    spx_daily_high REAL NOT NULL,
    spx_12d_ema    REAL NOT NULL,
    spx_25d_ema    REAL NOT NULL,
    mmth           REAL NOT NULL
);
"""


def get_connection(db_path: str) -> sqlite3.Connection:
    """
    Open (or create) the SQLite database at db_path.
    Enables WAL journal mode for ACID-safe concurrent access.
    Returns an open Connection with isolation_level=None (autocommit off;
    callers manage transactions explicitly).
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def create_schema(db_path: str) -> None:
    """
    Ensure the indicators table exists in the database at db_path.
    Idempotent — safe to call on an existing database.
    """
    conn = get_connection(db_path)
    try:
        conn.execute(CREATE_TABLE_SQL)
        conn.commit()
    finally:
        conn.close()
