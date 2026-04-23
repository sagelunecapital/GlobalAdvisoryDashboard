"""
Tests for src/macro/db/macro_schema.py

Covers:
  - Table creation (idempotent)
  - Correct columns: indicator_id, date, value, fetch_timestamp
  - Composite primary key on (indicator_id, date)
  - WAL mode enabled
  - Index idx_macro_indicator_date exists
"""

import sqlite3
import pytest

from src.macro.db.macro_schema import create_macro_schema, get_macro_connection


def test_create_macro_schema_creates_table(tmp_db):
    """Table macro_indicators is created when schema is initialized."""
    create_macro_schema(tmp_db)
    conn = sqlite3.connect(tmp_db)
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='macro_indicators'"
    )
    rows = cursor.fetchall()
    conn.close()
    assert len(rows) == 1, "macro_indicators table should exist after create_macro_schema()"


def test_create_macro_schema_idempotent(tmp_db):
    """Calling create_macro_schema twice does not raise or corrupt the table."""
    create_macro_schema(tmp_db)
    create_macro_schema(tmp_db)  # should not raise
    conn = sqlite3.connect(tmp_db)
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='macro_indicators'"
    )
    rows = cursor.fetchall()
    conn.close()
    assert len(rows) == 1


def test_macro_schema_columns(tmp_db):
    """Table has exactly the required columns: indicator_id, date, value, fetch_timestamp."""
    create_macro_schema(tmp_db)
    conn = sqlite3.connect(tmp_db)
    cursor = conn.execute("PRAGMA table_info(macro_indicators)")
    col_info = cursor.fetchall()
    conn.close()

    col_names = [row[1] for row in col_info]
    assert "indicator_id" in col_names
    assert "date" in col_names
    assert "value" in col_names
    assert "fetch_timestamp" in col_names
    assert len(col_names) == 4


def test_macro_schema_composite_primary_key(tmp_db):
    """Composite primary key (indicator_id, date) prevents duplicate (id, date) inserts."""
    create_macro_schema(tmp_db)
    conn = sqlite3.connect(tmp_db)
    conn.execute(
        "INSERT INTO macro_indicators VALUES (?, ?, ?, ?)",
        ("US_10Y_YIELD", "2024-01-01", 4.5, "2024-01-01T00:00:00Z"),
    )
    conn.commit()

    # Duplicate (indicator_id, date) must raise IntegrityError
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO macro_indicators VALUES (?, ?, ?, ?)",
            ("US_10Y_YIELD", "2024-01-01", 4.6, "2024-01-01T00:00:01Z"),
        )
        conn.commit()
    conn.close()


def test_macro_schema_different_id_same_date_allowed(tmp_db):
    """Different indicator_id can share the same date — only (id, date) pairs must be unique."""
    create_macro_schema(tmp_db)
    conn = sqlite3.connect(tmp_db)
    conn.execute(
        "INSERT INTO macro_indicators VALUES (?, ?, ?, ?)",
        ("US_10Y_YIELD", "2024-01-01", 4.5, "2024-01-01T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO macro_indicators VALUES (?, ?, ?, ?)",
        ("US_2Y_YIELD", "2024-01-01", 4.8, "2024-01-01T00:00:00Z"),
    )
    conn.commit()
    cursor = conn.execute("SELECT COUNT(*) FROM macro_indicators")
    count = cursor.fetchone()[0]
    conn.close()
    assert count == 2


def test_macro_schema_wal_mode(tmp_db):
    """WAL journal mode is enabled after get_macro_connection()."""
    create_macro_schema(tmp_db)
    conn = get_macro_connection(tmp_db)
    cursor = conn.execute("PRAGMA journal_mode")
    mode = cursor.fetchone()[0]
    conn.close()
    assert mode == "wal"


def test_macro_schema_index_exists(tmp_db):
    """Index idx_macro_indicator_date is created on macro_indicators."""
    create_macro_schema(tmp_db)
    conn = sqlite3.connect(tmp_db)
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_macro_indicator_date'"
    )
    rows = cursor.fetchall()
    conn.close()
    assert len(rows) == 1, "idx_macro_indicator_date index should exist"
