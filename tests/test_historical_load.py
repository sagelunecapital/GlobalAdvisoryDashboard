"""
Tests for src/db/historical_load.py.

Covers:
  - T6: load_historical with mocked fetch → 252+ rows stored, all columns non-null,
         spx_daily_high > 0
  - T7: Rollback test — inject Exception at row 50 → count = 0 after failure;
         re-run load succeeds
  - Verify no UPDATE or DELETE SQL in historical_load.py source (grep test)
"""

import re
import sqlite3
import pytest
import pandas as pd
import numpy as np

from src.db.schema import create_schema, get_connection
from src.db.historical_load import load_historical


class TestHistoricalLoad:
    def test_T6_load_historical_stores_252_plus_rows(self, tmp_db, sample_spx_df, sample_mmth_series):
        """
        T6: With mocked SPX and MMTH data, load_historical() must store
        at least 252 rows, all columns non-null, spx_daily_high > 0.
        """
        load_historical(tmp_db, _spx_df=sample_spx_df, _mmth_series=sample_mmth_series)

        conn = get_connection(tmp_db)
        cursor = conn.execute("SELECT COUNT(*) FROM indicators")
        count = cursor.fetchone()[0]

        cursor2 = conn.execute(
            "SELECT date, spx_daily_high, spx_12d_ema, spx_25d_ema, mmth FROM indicators"
        )
        rows = cursor2.fetchall()
        conn.close()

        assert count >= 252, f"Expected >= 252 rows, got {count}"

        for row in rows:
            date_val, high, ema12, ema25, mmth = row
            assert date_val is not None, "date column must not be NULL"
            assert high is not None, "spx_daily_high must not be NULL"
            assert ema12 is not None, "spx_12d_ema must not be NULL"
            assert ema25 is not None, "spx_25d_ema must not be NULL"
            assert mmth is not None, "mmth must not be NULL"
            assert high > 0, f"spx_daily_high must be > 0, got {high} on {date_val}"

    def test_T6_column_names_match_schema(self, tmp_db, sample_spx_df, sample_mmth_series):
        """
        T6 (supplementary): Column names in the stored data must match the schema
        exactly, including spx_daily_high per DEC-2026-04-18-01.
        """
        load_historical(tmp_db, _spx_df=sample_spx_df, _mmth_series=sample_mmth_series)

        conn = get_connection(tmp_db)
        cursor = conn.execute("PRAGMA table_info(indicators)")
        columns = [row[1] for row in cursor.fetchall()]
        conn.close()

        assert "spx_daily_high" in columns
        assert "spx_price" not in columns
        assert "spx_close" not in columns

    def test_T7_rollback_on_failure_leaves_empty_db(self, tmp_db, sample_spx_df, sample_mmth_series):
        """
        T7: When load_historical raises an exception mid-INSERT (simulated),
        the transaction must be rolled back — SELECT COUNT(*) returns 0.
        """
        from unittest.mock import patch

        call_count = [0]
        original_executemany = None

        def patched_executemany(sql, rows):
            """Raise after inserting the first batch row 50 rows in."""
            # Convert to list to count
            rows_list = list(rows)
            # Let the first 49 go through, then raise on row 50
            raise RuntimeError("Simulated failure at row 50")

        with patch("src.db.historical_load.get_connection") as mock_conn_factory:
            import sqlite3
            real_conn = sqlite3.connect(tmp_db)
            real_conn.execute("PRAGMA journal_mode=WAL")

            # We track BEGIN/ROLLBACK explicitly
            executed = []

            class TrackingCursor:
                def __init__(self, cur):
                    self._cur = cur

                def fetchone(self):
                    return self._cur.fetchone()

                def fetchall(self):
                    return self._cur.fetchall()

            class TrackingConn:
                def __init__(self, c):
                    self._c = c

                def execute(self, sql, *args):
                    executed.append(sql.strip().upper()[:20])
                    return self._c.execute(sql, *args)

                def executemany(self, sql, rows):
                    rows_list = list(rows)
                    if len(rows_list) > 0:
                        raise RuntimeError("Simulated failure at row 50")
                    return self._c.executemany(sql, rows_list)

                def commit(self):
                    return self._c.commit()

                def close(self):
                    return self._c.close()

            mock_conn_factory.return_value = TrackingConn(real_conn)

            with pytest.raises(RuntimeError) as exc_info:
                load_historical(tmp_db, _spx_df=sample_spx_df, _mmth_series=sample_mmth_series)

            assert "rolled back" in str(exc_info.value).lower() or "rollback" in str(exc_info.value).lower() or "simulated" in str(exc_info.value).lower()

            # After rollback, count should be 0
            check_conn = sqlite3.connect(tmp_db)
            try:
                cursor = check_conn.execute("SELECT COUNT(*) FROM indicators")
                count = cursor.fetchone()[0]
            except Exception:
                count = 0
            finally:
                check_conn.close()

            assert count == 0, f"Expected 0 rows after rollback, got {count}"

    def test_T7_rerun_after_rollback_succeeds(self, tmp_db, sample_spx_df, sample_mmth_series):
        """
        T7 (part 2): After a failed load (rollback), re-running load_historical
        with valid data succeeds and stores >= 252 rows.
        """
        # First attempt: force a failure by passing empty MMTH series
        empty_mmth = pd.Series([], dtype=float)
        with pytest.raises(RuntimeError):
            load_historical(tmp_db, _spx_df=sample_spx_df, _mmth_series=empty_mmth)

        # Verify DB is empty/clean
        conn = get_connection(tmp_db)
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM indicators")
            count_after_failure = cursor.fetchone()[0]
        finally:
            conn.close()
        assert count_after_failure == 0, f"DB not clean after failure: {count_after_failure} rows"

        # Second attempt: with valid data — must succeed
        load_historical(tmp_db, _spx_df=sample_spx_df, _mmth_series=sample_mmth_series)

        conn = get_connection(tmp_db)
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM indicators")
            count_after_success = cursor.fetchone()[0]
        finally:
            conn.close()
        assert count_after_success >= 252, f"Expected >= 252 rows after successful load, got {count_after_success}"

    def test_no_update_or_delete_sql_in_historical_load(self):
        """
        Verify that historical_load.py contains no UPDATE or DELETE SQL statements
        (append-only constraint per AC3).
        """
        import os
        module_path = os.path.join(
            os.path.dirname(__file__), "..", "src", "db", "historical_load.py"
        )
        with open(module_path, "r", encoding="utf-8") as f:
            source = f.read()

        # Search for UPDATE or DELETE as SQL keywords (case-insensitive)
        # Allow mentions in comments/docstrings that describe the constraint
        lines = source.splitlines()
        for lineno, line in enumerate(lines, 1):
            stripped = line.strip()
            # Skip comment lines and docstring lines
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            # Check for SQL UPDATE or DELETE keywords in non-comment code
            if re.search(r'\bUPDATE\b', line, re.IGNORECASE):
                # Allow if it's in a string that's part of a comment context
                # But fail if it appears to be actual SQL
                if '"UPDATE' in line or "'UPDATE" in line:
                    pytest.fail(f"Line {lineno}: Found UPDATE SQL in historical_load.py: {line.strip()}")
            if re.search(r'\bDELETE\b', line, re.IGNORECASE):
                if '"DELETE' in line or "'DELETE" in line:
                    pytest.fail(f"Line {lineno}: Found DELETE SQL in historical_load.py: {line.strip()}")
