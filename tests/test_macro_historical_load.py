"""
Tests for src/macro/db/macro_historical_load.py

Covers:
  - All 32 indicators stored when _overrides provided
  - One indicator failure leaves 31 stored (per-indicator error isolation)
  - All-fail raises RuntimeError
  - Idempotency: run twice = no extra rows (INSERT OR IGNORE)
  - fetch_timestamp non-null on all stored rows
  - GDPNow tuple override works
  - results dict keys cover all 32 indicator IDs
"""

import sqlite3
import pytest
import pandas as pd
import numpy as np
from datetime import date, timedelta

from src.macro.db.macro_historical_load import load_macro_historical, ALL_INDICATOR_IDS
from src.macro.db.macro_schema import create_macro_schema


def _make_daily_series(n: int = 100, base: float = 100.0, name: str = "test") -> pd.Series:
    """Generate a pd.Series with business-day DatetimeIndex."""
    np.random.seed(hash(name) % (2**31))
    idx = pd.date_range(start="2022-01-03", periods=n, freq="B")
    vals = base + np.cumsum(np.random.randn(n) * 0.5)
    return pd.Series(vals, index=idx, name=name)


def _make_monthly_series(n: int = 36, base: float = 50.0, name: str = "test") -> pd.Series:
    """Generate a pd.Series with month-end DatetimeIndex."""
    idx = pd.date_range(start="2020-01-31", periods=n, freq="ME")
    vals = base + np.arange(n, dtype=float) * 0.1
    return pd.Series(vals, index=idx, name=name)


def _build_all_overrides() -> dict:
    """
    Build _overrides dict covering all 32 indicator IDs.
    Monthly indicators use monthly series, daily use daily series.
    """
    monthly_ids = {
        "CPI_YOY", "CORE_CPI_YOY", "PCE_YOY", "CORE_PCE_YOY", "PPI_YOY",
        "ISM_MFG_PMI", "ISM_SVC_PMI", "NFP", "UNRATE", "RETAIL_SALES_MOM",
    }
    overrides = {}
    for iid in ALL_INDICATOR_IDS:
        if iid == "GDPNOW":
            overrides[iid] = ("2024-04-10", 2.8)
        elif iid in monthly_ids:
            overrides[iid] = _make_monthly_series(n=36, name=iid)
        else:
            overrides[iid] = _make_daily_series(n=100, name=iid)
    return overrides


def _count_rows(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM macro_indicators").fetchone()[0]
    conn.close()
    return count


def _get_indicator_ids_in_db(db_path: str) -> set:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT DISTINCT indicator_id FROM macro_indicators"
    ).fetchall()
    conn.close()
    return {r[0] for r in rows}


class TestLoadMacroHistorical:

    def test_all_32_indicators_stored(self, tmp_db):
        """With full _overrides, all 32 indicator IDs are stored in the DB."""
        overrides = _build_all_overrides()

        results = load_macro_historical(tmp_db, _overrides=overrides)

        stored_ids = _get_indicator_ids_in_db(tmp_db)
        assert len(stored_ids) == 32, (
            f"Expected 32 indicator IDs, got {len(stored_ids)}. "
            f"Missing: {set(ALL_INDICATOR_IDS) - stored_ids}"
        )
        for iid in ALL_INDICATOR_IDS:
            assert iid in stored_ids, f"Missing indicator_id: {iid}"

    def test_results_dict_has_all_32_keys(self, tmp_db):
        """Results dict contains entries for all 32 indicator IDs."""
        overrides = _build_all_overrides()
        results = load_macro_historical(tmp_db, _overrides=overrides)

        for iid in ALL_INDICATOR_IDS:
            assert iid in results, f"Missing result key: {iid}"

    def test_all_results_ok_with_full_overrides(self, tmp_db):
        """All results are 'ok' when all overrides are valid."""
        overrides = _build_all_overrides()
        results = load_macro_historical(tmp_db, _overrides=overrides)

        failed = [(k, v) for k, v in results.items() if v != "ok"]
        assert failed == [], f"Expected all ok but got failures: {failed}"

    def test_one_failure_leaves_31_stored(self, tmp_db):
        """When one indicator fails, 31 others are still stored successfully."""
        overrides = _build_all_overrides()
        # Remove GDPNOW override — replace with invalid tuple to cause failure
        overrides["GDPNOW"] = ("bad-date", float("nan"))  # nan value will fail REAL constraint

        results = load_macro_historical(tmp_db, _overrides=overrides)

        # GDPNOW should fail
        assert results["GDPNOW"].startswith("error")

        # All others should be ok
        ok_ids = [k for k, v in results.items() if v == "ok"]
        assert len(ok_ids) >= 31, (
            f"Expected ≥31 ok indicators but got {len(ok_ids)}. "
            f"Errors: {[(k, v) for k, v in results.items() if v != 'ok']}"
        )

        # 31 indicator IDs in DB
        stored_ids = _get_indicator_ids_in_db(tmp_db)
        assert len(stored_ids) >= 31

    def test_all_fail_raises_runtime_error(self, tmp_db):
        """RuntimeError raised when ALL indicators fail."""
        # Provide overrides with very short series (<52 daily / <12 monthly rows)
        overrides = {}
        monthly_ids = {
            "CPI_YOY", "CORE_CPI_YOY", "PCE_YOY", "CORE_PCE_YOY", "PPI_YOY",
            "ISM_MFG_PMI", "ISM_SVC_PMI", "NFP", "UNRATE", "RETAIL_SALES_MOM",
        }
        for iid in ALL_INDICATOR_IDS:
            if iid == "GDPNOW":
                # invalid float NaN — cannot be stored as REAL
                overrides[iid] = ("2024-01-01", float("nan"))
            elif iid in monthly_ids:
                # 1 row — below MIN_MONTHLY_ROWS=12
                idx = pd.date_range(start="2024-01-31", periods=1, freq="ME")
                overrides[iid] = pd.Series([50.0], index=idx, name=iid)
            else:
                # 5 rows — below MIN_DAILY_ROWS=52
                idx = pd.date_range(start="2024-01-03", periods=5, freq="B")
                overrides[iid] = pd.Series([100.0] * 5, index=idx, name=iid)

        with pytest.raises(RuntimeError, match="ALL"):
            load_macro_historical(tmp_db, _overrides=overrides)

    def test_idempotency_run_twice_no_extra_rows(self, tmp_db):
        """Running load twice produces no extra rows — INSERT OR IGNORE."""
        overrides = _build_all_overrides()

        results1 = load_macro_historical(tmp_db, _overrides=overrides)
        count_after_first = _count_rows(tmp_db)

        results2 = load_macro_historical(tmp_db, _overrides=overrides)
        count_after_second = _count_rows(tmp_db)

        assert count_after_first == count_after_second, (
            f"Row count changed on second run: {count_after_first} → {count_after_second}"
        )

    def test_fetch_timestamp_non_null_on_all_rows(self, tmp_db):
        """Every stored row has a non-null fetch_timestamp."""
        overrides = _build_all_overrides()
        load_macro_historical(tmp_db, _overrides=overrides)

        conn = sqlite3.connect(tmp_db)
        null_rows = conn.execute(
            "SELECT COUNT(*) FROM macro_indicators WHERE fetch_timestamp IS NULL"
        ).fetchone()[0]
        conn.close()

        assert null_rows == 0, f"Found {null_rows} rows with null fetch_timestamp"

    def test_gdpnow_tuple_override(self, tmp_db):
        """GDPNow (date, value) tuple override is stored as a single record."""
        overrides = _build_all_overrides()
        overrides["GDPNOW"] = ("2024-04-10", 3.1)

        results = load_macro_historical(tmp_db, _overrides=overrides)

        assert results["GDPNOW"] == "ok"

        conn = sqlite3.connect(tmp_db)
        rows = conn.execute(
            "SELECT date, value FROM macro_indicators WHERE indicator_id = 'GDPNOW'"
        ).fetchall()
        conn.close()

        assert len(rows) == 1
        assert rows[0][0] == "2024-04-10"
        assert abs(rows[0][1] - 3.1) < 1e-6

    def test_minimum_observation_counts(self, tmp_db):
        """Daily indicators have ≥52 rows; monthly indicators have ≥12 rows in DB."""
        overrides = _build_all_overrides()
        load_macro_historical(tmp_db, _overrides=overrides)

        monthly_ids = {
            "CPI_YOY", "CORE_CPI_YOY", "PCE_YOY", "CORE_PCE_YOY", "PPI_YOY",
            "ISM_MFG_PMI", "ISM_SVC_PMI", "NFP", "UNRATE", "RETAIL_SALES_MOM",
        }

        conn = sqlite3.connect(tmp_db)
        for iid in ALL_INDICATOR_IDS:
            if iid == "GDPNOW":
                # GDPNow stores 1 row (most recent estimate)
                count = conn.execute(
                    "SELECT COUNT(*) FROM macro_indicators WHERE indicator_id = ?", (iid,)
                ).fetchone()[0]
                assert count >= 1, f"{iid}: expected ≥1 row, got {count}"
            elif iid in monthly_ids:
                count = conn.execute(
                    "SELECT COUNT(*) FROM macro_indicators WHERE indicator_id = ?", (iid,)
                ).fetchone()[0]
                assert count >= 12, f"{iid}: expected ≥12 rows, got {count}"
            else:
                count = conn.execute(
                    "SELECT COUNT(*) FROM macro_indicators WHERE indicator_id = ?", (iid,)
                ).fetchone()[0]
                assert count >= 52, f"{iid}: expected ≥52 rows, got {count}"
        conn.close()

    def test_schema_fields_present(self, tmp_db):
        """All stored rows have indicator_id, date, value fields (AC9 for E03S02 compatibility)."""
        overrides = _build_all_overrides()
        load_macro_historical(tmp_db, _overrides=overrides)

        conn = sqlite3.connect(tmp_db)
        # Spot-check one indicator
        rows = conn.execute(
            "SELECT indicator_id, date, value FROM macro_indicators "
            "WHERE indicator_id = 'US_10Y_YIELD' LIMIT 5"
        ).fetchall()
        conn.close()

        assert len(rows) == 5
        for row in rows:
            assert row[0] == "US_10Y_YIELD"
            assert row[1] is not None and len(row[1]) == 10  # YYYY-MM-DD
            assert isinstance(row[2], float)

    def test_per_indicator_error_isolation_multiple_failures(self, tmp_db):
        """Multiple indicator failures do not block successful ones from storing."""
        overrides = _build_all_overrides()

        # Make 5 indicators fail with too-short series
        failing = ["CPI_YOY", "DXY", "GOLD_FRONT", "US_10Y_YIELD", "UNRATE"]
        monthly_ids = {"CPI_YOY", "UNRATE"}
        for iid in failing:
            if iid in monthly_ids:
                idx = pd.date_range(start="2024-01-31", periods=1, freq="ME")
                overrides[iid] = pd.Series([50.0], index=idx, name=iid)
            else:
                idx = pd.date_range(start="2024-01-03", periods=5, freq="B")
                overrides[iid] = pd.Series([100.0] * 5, index=idx, name=iid)

        results = load_macro_historical(tmp_db, _overrides=overrides)

        # Failing indicators should be marked as errors
        for iid in failing:
            assert results[iid].startswith("error"), (
                f"{iid} should have failed but got: {results[iid]}"
            )

        # Remaining 27 (32 - 5) should be ok
        ok_count = sum(1 for v in results.values() if v == "ok")
        assert ok_count >= 27, (
            f"Expected ≥27 ok indicators but got {ok_count}. "
            f"Errors: {[(k, v) for k, v in results.items() if v != 'ok']}"
        )
