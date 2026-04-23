"""
Tests for src/macro/db/macro_append.py

Covers:
  - Batch INSERT works
  - INSERT OR IGNORE idempotency (duplicate (indicator_id, date) skipped)
  - fetch_timestamp stored non-null
  - Returns correct insert count
"""

import sqlite3
import pytest

from src.macro.db.macro_append import append_macro_records
from src.macro.db.macro_schema import create_macro_schema


def _read_all(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        "SELECT indicator_id, date, value, fetch_timestamp FROM macro_indicators "
        "ORDER BY indicator_id, date"
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


def test_append_inserts_batch(tmp_db):
    """Batch of records is inserted correctly."""
    create_macro_schema(tmp_db)
    records = [
        ("US_10Y_YIELD", "2024-01-01", 4.5, "2024-01-01T00:00:00Z"),
        ("US_10Y_YIELD", "2024-01-02", 4.52, "2024-01-01T00:00:00Z"),
        ("CPI_YOY", "2024-01-31", 3.1, "2024-01-01T00:00:00Z"),
    ]
    count = append_macro_records(tmp_db, records)
    assert count == 3

    rows = _read_all(tmp_db)
    assert len(rows) == 3


def test_append_returns_insert_count(tmp_db):
    """Return value equals the number of rows actually inserted."""
    create_macro_schema(tmp_db)
    records = [
        ("DXY", "2024-03-01", 104.2, "2024-03-01T10:00:00Z"),
        ("DXY", "2024-03-02", 104.5, "2024-03-01T10:00:00Z"),
    ]
    count = append_macro_records(tmp_db, records)
    assert count == 2


def test_append_idempotent_ignore_duplicate(tmp_db):
    """Duplicate (indicator_id, date) is silently ignored — INSERT OR IGNORE."""
    create_macro_schema(tmp_db)
    records = [
        ("GOLD_FRONT", "2024-05-01", 2300.0, "2024-05-01T12:00:00Z"),
    ]
    count1 = append_macro_records(tmp_db, records)
    assert count1 == 1

    # Second insert with same (indicator_id, date) — must be ignored
    count2 = append_macro_records(tmp_db, records)
    assert count2 == 0

    rows = _read_all(tmp_db)
    # Only one row should exist
    gold_rows = [r for r in rows if r[0] == "GOLD_FRONT"]
    assert len(gold_rows) == 1
    # Original value is preserved
    assert gold_rows[0][2] == 2300.0


def test_append_partial_duplicate(tmp_db):
    """Only new (indicator_id, date) pairs are inserted; existing ones ignored."""
    create_macro_schema(tmp_db)
    initial = [
        ("WTI_FRONT", "2024-06-01", 80.0, "2024-06-01T00:00:00Z"),
        ("WTI_FRONT", "2024-06-02", 81.0, "2024-06-01T00:00:00Z"),
    ]
    append_macro_records(tmp_db, initial)

    # Add 2024-06-02 (dup) + new 2024-06-03
    mixed = [
        ("WTI_FRONT", "2024-06-02", 99.0, "2024-06-02T00:00:00Z"),  # dup — ignored
        ("WTI_FRONT", "2024-06-03", 82.0, "2024-06-02T00:00:00Z"),  # new
    ]
    count = append_macro_records(tmp_db, mixed)
    assert count == 1  # only one new row

    rows = _read_all(tmp_db)
    wti_rows = [r for r in rows if r[0] == "WTI_FRONT"]
    assert len(wti_rows) == 3  # 3 unique dates
    # Value for 2024-06-02 should be the original 81.0
    jun02 = [r for r in wti_rows if r[1] == "2024-06-02"][0]
    assert jun02[2] == 81.0


def test_append_fetch_timestamp_non_null(tmp_db):
    """fetch_timestamp is stored and is non-null."""
    create_macro_schema(tmp_db)
    ts = "2024-07-15T08:30:00Z"
    records = [("UNRATE", "2024-07-31", 4.1, ts)]
    append_macro_records(tmp_db, records)

    rows = _read_all(tmp_db)
    assert len(rows) == 1
    assert rows[0][3] == ts
    assert rows[0][3] is not None


def test_append_empty_list(tmp_db):
    """Empty records list returns 0 inserts without error."""
    create_macro_schema(tmp_db)
    count = append_macro_records(tmp_db, [])
    assert count == 0


def test_append_creates_schema_if_absent(tmp_db):
    """append_macro_records creates the schema if not yet initialized."""
    # Do NOT call create_macro_schema first
    records = [("NFP", "2024-08-31", 150000.0, "2024-08-01T00:00:00Z")]
    count = append_macro_records(tmp_db, records)
    assert count == 1

    rows = _read_all(tmp_db)
    assert len(rows) == 1
