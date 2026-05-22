"""
DB schema and connection factory for the liquidity_series table.

Table: liquidity_series
  series_id        TEXT NOT NULL    -- named series ID (e.g., WRESBAL, BTC_WEEKLY)
  date             TEXT NOT NULL    -- ISO-8601 YYYY-MM-DD
  value            REAL NOT NULL    -- numeric observation
  fetch_timestamp  TEXT NOT NULL    -- UTC ISO-8601 when record was fetched

Primary key: (series_id, date) -- composite, no overwrites possible.
WAL mode enabled for ACID guarantees.

NOTE: This module is self-contained -- it does NOT import from src.db or src.macro.
"""

import sqlite3
from pathlib import Path


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS liquidity_series (
    series_id        TEXT NOT NULL,
    date             TEXT NOT NULL,
    value            REAL NOT NULL,
    fetch_timestamp  TEXT NOT NULL,
    PRIMARY KEY (series_id, date)
);
"""

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_liquidity_series_date
    ON liquidity_series (series_id, date DESC);
"""


def get_liquidity_connection(db_path: str) -> sqlite3.Connection:
    """
    Open (or create) the SQLite database at db_path.
    Enables WAL journal mode for ACID-safe concurrent access.
    Returns an open Connection (autocommit off; callers manage transactions).
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def create_liquidity_schema(db_path: str) -> None:
    """
    Ensure the liquidity_series table and index exist in the database at db_path.
    Idempotent -- safe to call on an existing database.
    """
    conn = get_liquidity_connection(db_path)
    try:
        conn.execute(CREATE_TABLE_SQL)
        conn.execute(CREATE_INDEX_SQL)
        conn.commit()
    finally:
        conn.close()
