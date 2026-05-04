"""
Tests for src/db/schema.py.

Covers:
  - Table 'indicators' exists after create_schema()
  - All 5 required columns present: date, spx_daily_high, spx_12d_ema, spx_25d_ema, mmth
  - 'date' is the primary key
  - WAL journal mode is enabled
"""

import sqlite3
import pytest

from src.db.schema import create_schema, get_connection


class TestSchemaCreation:
    def test_indicators_table_exists(self, tmp_db):
        """Table 'indicators' must exist after create_schema()."""
        create_schema(tmp_db)
        conn = get_connection(tmp_db)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='indicators'"
        )
        result = cursor.fetchone()
        conn.close()
        assert result is not None, "Table 'indicators' not found after create_schema()"
        assert result[0] == "indicators"

    def test_all_required_columns_present(self, tmp_db):
        """All 5 columns must be present with correct names."""
        create_schema(tmp_db)
        conn = get_connection(tmp_db)
        cursor = conn.execute("PRAGMA table_info(indicators)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()

        required = {"date", "spx_daily_high", "spx_12d_ema", "spx_25d_ema", "mmth"}
        assert required == columns, (
            f"Column mismatch. Expected: {required}, Found: {columns}"
        )

    def test_date_is_primary_key(self, tmp_db):
        """'date' column must be declared as the primary key."""
        create_schema(tmp_db)
        conn = get_connection(tmp_db)
        cursor = conn.execute("PRAGMA table_info(indicators)")
        rows = cursor.fetchall()
        conn.close()

        # PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
        pk_columns = [row[1] for row in rows if row[5] == 1]
        assert "date" in pk_columns, (
            f"'date' is not the primary key. Primary key columns: {pk_columns}"
        )

    def test_wal_journal_mode_enabled(self, tmp_db):
        """WAL journal mode must be active after get_connection()."""
        create_schema(tmp_db)
        conn = get_connection(tmp_db)
        cursor = conn.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        conn.close()
        assert mode == "wal", f"Expected WAL journal mode, got: {mode}"

    def test_create_schema_is_idempotent(self, tmp_db):
        """Calling create_schema() twice must not raise or corrupt the DB."""
        create_schema(tmp_db)
        create_schema(tmp_db)  # second call — must be safe
        conn = get_connection(tmp_db)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='indicators'"
        )
        result = cursor.fetchone()
        conn.close()
        assert result is not None

    def test_spx_daily_high_column_not_named_spx_price(self, tmp_db):
        """Enforce DEC-2026-04-18-01: column must be 'spx_daily_high', not 'spx_price'."""
        create_schema(tmp_db)
        conn = get_connection(tmp_db)
        cursor = conn.execute("PRAGMA table_info(indicators)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()
        assert "spx_daily_high" in columns, "Column 'spx_daily_high' missing"
        assert "spx_price" not in columns, "Column 'spx_price' must not exist (use spx_daily_high)"
        assert "spx_close" not in columns, "Column 'spx_close' must not exist (use spx_daily_high)"
