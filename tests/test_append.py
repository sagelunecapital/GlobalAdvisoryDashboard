"""
Tests for src/db/append.py.

Covers:
  - T8: Append new row with future date → count +1; existing rows unchanged
  - T9: Idempotency — call append_day() twice with same date → count +1 (not +2)
  - T10: Persistence — write row, close connection, open new connection, row is retrievable
"""

import sqlite3
import pytest

from src.db.schema import create_schema, get_connection
from src.db.append import append_day


# Sample indicator values for testing
SAMPLE_ROW = {
    "date": "2099-01-01",  # Far-future date ensures no collision with real data
    "spx_daily_high": 5500.25,
    "spx_12d_ema": 5490.10,
    "spx_25d_ema": 5480.05,
    "mmth": 62.5,
}

SAMPLE_ROW_2 = {
    "date": "2099-01-02",
    "spx_daily_high": 5510.00,
    "spx_12d_ema": 5495.00,
    "spx_25d_ema": 5482.00,
    "mmth": 63.0,
}


def _count_rows(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute("SELECT COUNT(*) FROM indicators")
        return cursor.fetchone()[0]
    finally:
        conn.close()


def _get_row(db_path: str, date: str):
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            "SELECT date, spx_daily_high, spx_12d_ema, spx_25d_ema, mmth "
            "FROM indicators WHERE date = ?",
            (date,),
        )
        return cursor.fetchone()
    finally:
        conn.close()


class TestAppend:
    def test_T8_append_new_row_increases_count(self, tmp_db):
        """
        T8: Appending a new row to an empty DB results in count = 1.
        Appending a second distinct row results in count = 2.
        """
        create_schema(tmp_db)
        assert _count_rows(tmp_db) == 0

        append_day(tmp_db, **SAMPLE_ROW)
        assert _count_rows(tmp_db) == 1, "Count should be 1 after first append"

        append_day(tmp_db, **SAMPLE_ROW_2)
        assert _count_rows(tmp_db) == 2, "Count should be 2 after second append"

    def test_T8_existing_rows_unchanged_after_append(self, tmp_db):
        """
        T8: Appending a new row must not modify existing rows.
        """
        create_schema(tmp_db)
        append_day(tmp_db, **SAMPLE_ROW)

        # Retrieve original row
        original = _get_row(tmp_db, SAMPLE_ROW["date"])
        assert original is not None

        # Append a different row
        append_day(tmp_db, **SAMPLE_ROW_2)

        # Original row must be unchanged
        after_append = _get_row(tmp_db, SAMPLE_ROW["date"])
        assert after_append == original, (
            f"Original row was modified after appending a different row. "
            f"Before: {original}, After: {after_append}"
        )

    def test_T9_idempotency_same_date_twice_count_plus_one(self, tmp_db):
        """
        T9: Calling append_day() twice with the same date must result in
        count = 1, not 2 (INSERT OR IGNORE idempotency).
        """
        create_schema(tmp_db)

        append_day(tmp_db, **SAMPLE_ROW)
        count_after_first = _count_rows(tmp_db)
        assert count_after_first == 1

        # Call again with same date — should be ignored
        append_day(tmp_db, **SAMPLE_ROW)
        count_after_second = _count_rows(tmp_db)
        assert count_after_second == 1, (
            f"Duplicate insert was NOT ignored: count went from 1 to {count_after_second}"
        )

    def test_T10_persistence_row_survives_connection_close(self, tmp_db):
        """
        T10: Row written by append_day() must be retrievable after
        the connection is closed and a new connection is opened.
        """
        create_schema(tmp_db)
        append_day(tmp_db, **SAMPLE_ROW)

        # Open a completely fresh connection (simulating application restart)
        fresh_conn = sqlite3.connect(tmp_db)
        try:
            cursor = fresh_conn.execute(
                "SELECT date, spx_daily_high, spx_12d_ema, spx_25d_ema, mmth "
                "FROM indicators WHERE date = ?",
                (SAMPLE_ROW["date"],),
            )
            row = cursor.fetchone()
        finally:
            fresh_conn.close()

        assert row is not None, (
            f"Row for date {SAMPLE_ROW['date']} not found after connection close + reopen"
        )
        assert row[0] == SAMPLE_ROW["date"]
        assert abs(row[1] - SAMPLE_ROW["spx_daily_high"]) < 0.001
        assert abs(row[2] - SAMPLE_ROW["spx_12d_ema"]) < 0.001
        assert abs(row[3] - SAMPLE_ROW["spx_25d_ema"]) < 0.001
        assert abs(row[4] - SAMPLE_ROW["mmth"]) < 0.001

    def test_T10_persistence_multiple_rows_survive_restart(self, tmp_db):
        """
        T10 (extended): Multiple rows must all survive a connection close.
        """
        create_schema(tmp_db)
        append_day(tmp_db, **SAMPLE_ROW)
        append_day(tmp_db, **SAMPLE_ROW_2)

        # New connection
        fresh_conn = sqlite3.connect(tmp_db)
        try:
            cursor = fresh_conn.execute("SELECT COUNT(*) FROM indicators")
            count = cursor.fetchone()[0]
        finally:
            fresh_conn.close()

        assert count == 2, f"Expected 2 rows after reconnect, got {count}"

    def test_no_update_or_delete_sql_in_append(self):
        """
        Verify that append.py contains no UPDATE or DELETE SQL statements
        (append-only constraint per AC3).
        """
        import os, re
        module_path = os.path.join(
            os.path.dirname(__file__), "..", "src", "db", "append.py"
        )
        with open(module_path, "r", encoding="utf-8") as f:
            source = f.read()

        lines = source.splitlines()
        for lineno, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            if '"UPDATE' in line or "'UPDATE" in line:
                pytest.fail(f"Line {lineno}: Found UPDATE SQL in append.py: {line.strip()}")
            if '"DELETE' in line or "'DELETE" in line:
                pytest.fail(f"Line {lineno}: Found DELETE SQL in append.py: {line.strip()}")
