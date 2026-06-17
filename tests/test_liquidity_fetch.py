"""
Tests for src/liquidity/ module -- E02S01 acceptance criteria.

Covers:
  - AC5: Second run does not duplicate records (incremental logic)
  - AC6: FRED failure for one series does not crash; error message contains series name
  - AC7: BTC failure does not block FRED fetches
  - AC8: Stored records have all 4 required fields (series_id, date, value, fetch_timestamp)

All tests use _overrides -- no live API calls.
"""

import sqlite3
import pytest
import pandas as pd
import numpy as np
from datetime import date, timedelta

from src.liquidity.historical_load import load_liquidity_historical, ALL_SERIES_IDS
from src.liquidity.db.liquidity_schema import create_liquidity_schema
from src.liquidity.db.liquidity_append import get_latest_date


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_weekly_records(n: int = 52, start: str = "2020-01-03") -> list:
    """
    Generate n weekly (date_str, float_value) tuples starting from start.
    Dates spaced 7 days apart.
    """
    base = date.fromisoformat(start)
    records = []
    for i in range(n):
        d = base + timedelta(weeks=i)
        records.append((d.strftime("%Y-%m-%d"), float(1000 + i)))
    return records


def _make_monthly_records(n: int = 24, start: str = "2020-01-31") -> list:
    """
    Generate n monthly (date_str, float_value) tuples.
    Approximates month-end dates.
    """
    import calendar
    records = []
    year, month = 2020, 1
    for i in range(n):
        last_day = calendar.monthrange(year, month)[1]
        d = date(year, month, last_day)
        records.append((d.strftime("%Y-%m-%d"), float(500 + i)))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return records


def _build_full_overrides() -> dict:
    """Build _overrides covering all 7 series with valid data."""
    overrides = {}
    for sid in ["WRESBAL", "WALCL", "WDTGAL", "WLRRAL"]:
        overrides[sid] = _make_weekly_records(52)
    overrides["BOPGSTB"] = _make_monthly_records(24)
    overrides["BTC_WEEKLY"] = _make_weekly_records(52, start="2020-01-03")
    overrides["BTC_MONTHLY"] = _make_monthly_records(24, start="2020-01-31")
    return overrides


def _count_rows(db_path: str, series_id: str = None) -> int:
    conn = sqlite3.connect(db_path)
    if series_id:
        count = conn.execute(
            "SELECT COUNT(*) FROM liquidity_series WHERE series_id = ?",
            (series_id,)
        ).fetchone()[0]
    else:
        count = conn.execute("SELECT COUNT(*) FROM liquidity_series").fetchone()[0]
    conn.close()
    return count


def _get_all_rows(db_path: str) -> list:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT series_id, date, value, fetch_timestamp FROM liquidity_series"
    ).fetchall()
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# AC5: Incremental / no-duplicate tests
# ---------------------------------------------------------------------------

class TestAC5Incremental:

    def test_second_run_does_not_duplicate_records(self, tmp_db):
        """
        Running load twice with the same data produces no extra rows.
        INSERT OR IGNORE must skip records already present.
        """
        overrides = _build_full_overrides()

        results1 = load_liquidity_historical(tmp_db, _overrides=overrides)
        count_after_first = _count_rows(tmp_db)

        results2 = load_liquidity_historical(tmp_db, _overrides=overrides)
        count_after_second = _count_rows(tmp_db)

        assert count_after_first == count_after_second, (
            f"Row count changed on second run: "
            f"{count_after_first} -> {count_after_second}"
        )

    def test_second_run_reports_zero_inserted(self, tmp_db):
        """
        Second run with same data: each series reports 0 new records inserted.
        """
        overrides = _build_full_overrides()

        load_liquidity_historical(tmp_db, _overrides=overrides)
        results2 = load_liquidity_historical(tmp_db, _overrides=overrides)

        for sid in ALL_SERIES_IDS:
            assert results2[sid].startswith("ok"), f"{sid} should be ok on second run"
            assert "0 records inserted" in results2[sid], (
                f"{sid}: expected 0 records on second run, got: {results2[sid]}"
            )

    def test_incremental_appends_only_new_dates(self, tmp_db):
        """
        First run loads 10 records; second run provides 5 new records.
        Only the 5 new records are inserted on the second run.
        """
        # First load: 10 weeks
        first_records = _make_weekly_records(10)
        overrides_first = _build_full_overrides()
        overrides_first["WRESBAL"] = first_records
        load_liquidity_historical(tmp_db, _overrides=overrides_first)
        count_after_first = _count_rows(tmp_db, "WRESBAL")
        assert count_after_first == 10

        # Second load: 15 weeks (first 10 already stored, 5 new)
        all_records = _make_weekly_records(15)
        overrides_second = _build_full_overrides()
        overrides_second["WRESBAL"] = all_records
        load_liquidity_historical(tmp_db, _overrides=overrides_second)
        count_after_second = _count_rows(tmp_db, "WRESBAL")
        assert count_after_second == 15, (
            f"Expected 15 WRESBAL records after second run, got {count_after_second}"
        )

    def test_historical_data_not_overwritten(self, tmp_db):
        """
        Records inserted on first run are unchanged after second run.
        """
        overrides = _build_full_overrides()
        load_liquidity_historical(tmp_db, _overrides=overrides)

        # Capture rows after first run
        rows_first = set(_get_all_rows(tmp_db))

        load_liquidity_historical(tmp_db, _overrides=overrides)
        rows_second = set(_get_all_rows(tmp_db))

        # All first-run rows must still exist
        missing = rows_first - rows_second
        assert not missing, f"Rows from first run are missing after second run: {missing}"


# ---------------------------------------------------------------------------
# AC6: FRED failure for one series -- visible error, no crash
# ---------------------------------------------------------------------------

class TestAC6FREDFailure:

    def test_fred_failure_one_series_does_not_crash(self, tmp_db):
        """
        FRED failure for WRESBAL does not crash -- other series continue.
        """
        overrides = _build_full_overrides()
        overrides["WRESBAL"] = RuntimeError("simulated FRED API failure for WRESBAL")

        # Must not raise
        results = load_liquidity_historical(tmp_db, _overrides=overrides)

        assert "WRESBAL" in results
        assert results["WRESBAL"].startswith("error"), (
            f"Expected error for WRESBAL, got: {results['WRESBAL']}"
        )

    def test_fred_failure_error_contains_series_name(self, tmp_db):
        """
        Error message for failed FRED series must contain the series name (AC6).
        """
        overrides = _build_full_overrides()
        overrides["WALCL"] = RuntimeError("simulated timeout")

        results = load_liquidity_historical(tmp_db, _overrides=overrides)

        assert "WALCL" in results["WALCL"], (
            f"Error message must identify the series name. Got: {results['WALCL']}"
        )

    def test_fred_failure_other_series_still_succeed(self, tmp_db):
        """
        When WRESBAL fails, all other FRED series and BTC series succeed.
        """
        overrides = _build_full_overrides()
        overrides["WRESBAL"] = RuntimeError("simulated FRED failure")

        results = load_liquidity_historical(tmp_db, _overrides=overrides)

        # WRESBAL failed
        assert results["WRESBAL"].startswith("error")

        # All others succeeded
        other_series = [s for s in ALL_SERIES_IDS if s != "WRESBAL"]
        for sid in other_series:
            assert results[sid].startswith("ok"), (
                f"{sid} should have succeeded but got: {results[sid]}"
            )

    def test_fred_failure_no_partial_silent_persist(self, tmp_db):
        """
        When WRESBAL fails, zero WRESBAL rows are persisted.
        """
        overrides = _build_full_overrides()
        overrides["WRESBAL"] = RuntimeError("simulated failure")

        load_liquidity_historical(tmp_db, _overrides=overrides)
        assert _count_rows(tmp_db, "WRESBAL") == 0, (
            "WRESBAL should have 0 rows when fetch failed"
        )

    def test_multiple_fred_failures_isolated(self, tmp_db):
        """
        Multiple FRED failures are each isolated -- remaining series succeed.
        """
        overrides = _build_full_overrides()
        overrides["WRESBAL"] = RuntimeError("fail1")
        overrides["WALCL"] = RuntimeError("fail2")
        overrides["BOPGSTB"] = RuntimeError("fail3")

        results = load_liquidity_historical(tmp_db, _overrides=overrides)

        for failed_sid in ["WRESBAL", "WALCL", "BOPGSTB"]:
            assert results[failed_sid].startswith("error"), (
                f"{failed_sid} should be error, got: {results[failed_sid]}"
            )

        for ok_sid in ["WDTGAL", "WLRRAL", "BTC_WEEKLY", "BTC_MONTHLY"]:
            assert results[ok_sid].startswith("ok"), (
                f"{ok_sid} should be ok, got: {results[ok_sid]}"
            )


# ---------------------------------------------------------------------------
# AC7: Bitcoin failure does not block FRED fetches
# ---------------------------------------------------------------------------

class TestAC7BitcoinFailure:

    def test_btc_failure_does_not_block_fred_fetches(self, tmp_db):
        """
        BTC_WEEKLY failure does not prevent FRED series from being fetched.
        """
        overrides = _build_full_overrides()
        overrides["BTC_WEEKLY"] = RuntimeError("simulated BTC outage")

        results = load_liquidity_historical(tmp_db, _overrides=overrides)

        # FRED series all succeeded
        for sid in ["WRESBAL", "WALCL", "WDTGAL", "WLRRAL", "BOPGSTB"]:
            assert results[sid].startswith("ok"), (
                f"{sid} should succeed despite BTC failure. Got: {results[sid]}"
            )

        # BTC_WEEKLY failed
        assert results["BTC_WEEKLY"].startswith("error")

    def test_both_btc_series_fail_fred_still_ok(self, tmp_db):
        """
        Both BTC_WEEKLY and BTC_MONTHLY failing does not block FRED fetches.
        """
        overrides = _build_full_overrides()
        overrides["BTC_WEEKLY"] = RuntimeError("BTC weekly down")
        overrides["BTC_MONTHLY"] = RuntimeError("BTC monthly down")

        results = load_liquidity_historical(tmp_db, _overrides=overrides)

        for sid in ["WRESBAL", "WALCL", "WDTGAL", "WLRRAL", "BOPGSTB"]:
            assert results[sid].startswith("ok"), (
                f"{sid} should succeed. Got: {results[sid]}"
            )

        for sid in ["BTC_WEEKLY", "BTC_MONTHLY"]:
            assert results[sid].startswith("error")

    def test_btc_failure_error_contains_series_name(self, tmp_db):
        """
        BTC failure error message must contain the series name.
        """
        overrides = _build_full_overrides()
        overrides["BTC_MONTHLY"] = RuntimeError("connection timeout")

        results = load_liquidity_historical(tmp_db, _overrides=overrides)

        assert "BTC_MONTHLY" in results["BTC_MONTHLY"], (
            f"Error must identify BTC_MONTHLY. Got: {results['BTC_MONTHLY']}"
        )

    def test_btc_failure_zero_btc_rows_in_db(self, tmp_db):
        """
        BTC failure results in zero BTC rows persisted.
        """
        overrides = _build_full_overrides()
        overrides["BTC_WEEKLY"] = RuntimeError("down")
        overrides["BTC_MONTHLY"] = RuntimeError("down")

        load_liquidity_historical(tmp_db, _overrides=overrides)

        assert _count_rows(tmp_db, "BTC_WEEKLY") == 0
        assert _count_rows(tmp_db, "BTC_MONTHLY") == 0


# ---------------------------------------------------------------------------
# AC8: All 4 required fields present in stored records
# ---------------------------------------------------------------------------

class TestAC8StoredRecordFields:

    def test_all_4_fields_present_in_stored_records(self, tmp_db):
        """
        Every stored record has series_id, date, value, fetch_timestamp.
        None of these fields may be NULL.
        """
        overrides = _build_full_overrides()
        load_liquidity_historical(tmp_db, _overrides=overrides)

        conn = sqlite3.connect(tmp_db)
        rows = conn.execute(
            "SELECT series_id, date, value, fetch_timestamp "
            "FROM liquidity_series"
        ).fetchall()
        conn.close()

        assert len(rows) > 0, "Expected rows in liquidity_series"
        for row in rows:
            series_id, date_val, value, fetch_ts = row
            assert series_id is not None and series_id != "", (
                f"series_id is null/empty: {row}"
            )
            assert date_val is not None and len(date_val) == 10, (
                f"date is null or wrong format (expected YYYY-MM-DD): {row}"
            )
            assert value is not None, f"value is null: {row}"
            assert isinstance(value, float), f"value is not float: {row}"
            assert fetch_ts is not None and fetch_ts != "", (
                f"fetch_timestamp is null/empty: {row}"
            )

    def test_fetch_timestamp_is_utc_iso8601(self, tmp_db):
        """
        fetch_timestamp must be UTC ISO-8601 format (YYYY-MM-DDTHH:MM:SSZ).
        """
        overrides = _build_full_overrides()
        load_liquidity_historical(tmp_db, _overrides=overrides)

        conn = sqlite3.connect(tmp_db)
        rows = conn.execute(
            "SELECT DISTINCT fetch_timestamp FROM liquidity_series"
        ).fetchall()
        conn.close()

        assert len(rows) > 0
        for (ts,) in rows:
            assert ts.endswith("Z"), f"fetch_timestamp must end with Z (UTC): {ts}"
            assert "T" in ts, f"fetch_timestamp must include T separator: {ts}"
            # Validate it parses as ISO-8601
            from datetime import datetime
            try:
                datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                pytest.fail(f"fetch_timestamp is not valid ISO-8601: {ts}")

    def test_date_format_is_yyyy_mm_dd(self, tmp_db):
        """
        All stored dates are in YYYY-MM-DD format.
        """
        overrides = _build_full_overrides()
        load_liquidity_historical(tmp_db, _overrides=overrides)

        conn = sqlite3.connect(tmp_db)
        rows = conn.execute("SELECT date FROM liquidity_series").fetchall()
        conn.close()

        from datetime import datetime
        for (d,) in rows:
            assert len(d) == 10, f"date must be 10 chars (YYYY-MM-DD), got: {d}"
            try:
                datetime.strptime(d, "%Y-%m-%d")
            except ValueError:
                pytest.fail(f"date is not valid YYYY-MM-DD: {d}")

    def test_series_id_values_match_expected(self, tmp_db):
        """
        series_id values in DB must match the canonical set of 7 IDs.
        """
        overrides = _build_full_overrides()
        load_liquidity_historical(tmp_db, _overrides=overrides)

        conn = sqlite3.connect(tmp_db)
        stored_ids = {
            r[0] for r in conn.execute(
                "SELECT DISTINCT series_id FROM liquidity_series"
            ).fetchall()
        }
        conn.close()

        expected_ids = set(ALL_SERIES_IDS)
        assert stored_ids == expected_ids, (
            f"series_id mismatch. Expected: {expected_ids}, Got: {stored_ids}"
        )

    def test_no_null_fields_in_any_row(self, tmp_db):
        """
        No row may have any NULL field (AC8 data integrity).
        """
        overrides = _build_full_overrides()
        load_liquidity_historical(tmp_db, _overrides=overrides)

        conn = sqlite3.connect(tmp_db)
        null_count = conn.execute(
            "SELECT COUNT(*) FROM liquidity_series "
            "WHERE series_id IS NULL OR date IS NULL "
            "   OR value IS NULL OR fetch_timestamp IS NULL"
        ).fetchone()[0]
        conn.close()

        assert null_count == 0, f"Found {null_count} rows with NULL fields"


# ---------------------------------------------------------------------------
# Additional integration tests
# ---------------------------------------------------------------------------

class TestIntegration:

    def test_all_7_series_loaded_on_clean_db(self, tmp_db):
        """
        Clean DB: all 7 series are stored after a successful load.
        """
        overrides = _build_full_overrides()
        results = load_liquidity_historical(tmp_db, _overrides=overrides)

        conn = sqlite3.connect(tmp_db)
        stored_ids = {
            r[0] for r in conn.execute(
                "SELECT DISTINCT series_id FROM liquidity_series"
            ).fetchall()
        }
        conn.close()

        assert stored_ids == set(ALL_SERIES_IDS), (
            f"Missing series: {set(ALL_SERIES_IDS) - stored_ids}"
        )

    def test_results_dict_has_all_7_keys(self, tmp_db):
        """
        Results dict always has all 7 series IDs as keys.
        """
        overrides = _build_full_overrides()
        results = load_liquidity_historical(tmp_db, _overrides=overrides)

        for sid in ALL_SERIES_IDS:
            assert sid in results, f"Missing result key: {sid}"

    def test_all_fail_raises_runtime_error(self, tmp_db):
        """
        RuntimeError raised when ALL 7 series fail.
        """
        overrides = {
            sid: RuntimeError(f"simulated failure for {sid}")
            for sid in ALL_SERIES_IDS
        }

        with pytest.raises(RuntimeError, match="ALL"):
            load_liquidity_historical(tmp_db, _overrides=overrides)

    def test_get_latest_date_returns_none_on_empty_db(self, tmp_db):
        """
        get_latest_date returns None when no records exist.
        """
        create_liquidity_schema(tmp_db)
        result = get_latest_date(tmp_db, "WRESBAL")
        assert result is None

    def test_get_latest_date_returns_max_date(self, tmp_db):
        """
        get_latest_date returns the latest stored date for a series.
        """
        from src.liquidity.db.liquidity_append import append_liquidity_records
        create_liquidity_schema(tmp_db)

        records = [
            ("WRESBAL", "2023-01-06", 3000.0, "2026-01-01T00:00:00Z"),
            ("WRESBAL", "2023-01-13", 3100.0, "2026-01-01T00:00:00Z"),
            ("WRESBAL", "2023-01-20", 3200.0, "2026-01-01T00:00:00Z"),
        ]
        append_liquidity_records(tmp_db, records)

        latest = get_latest_date(tmp_db, "WRESBAL")
        assert latest == "2023-01-20"
