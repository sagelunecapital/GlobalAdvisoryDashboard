"""
Liquidity historical data load orchestrator -- AC1-AC8.

Fetches all 7 liquidity series and persists them to the liquidity_series table:
  FRED weekly (5):  WRESBAL, WALCL, WDTGAL, WLRRAL (weekly), BOPGSTB (monthly)
  Bitcoin (2):      BTC_WEEKLY, BTC_MONTHLY

Incremental logic (AC5):
  On each run, the latest stored date for each series is queried first.
  Only dates after that date are fetched from the source.
  Historical data is never overwritten or deleted (INSERT OR IGNORE).

Error isolation (AC6, AC7):
  Each series is fetched in its own try/except block.
  FRED failure for one series surfaces a visible error identifying that series,
  but does not block other FRED series from fetching.
  Bitcoin failure surfaces a visible error but does not block FRED fetches.

All fetched records include: series_id, date, value, fetch_timestamp (UTC ISO-8601).

_overrides parameter: dict[series_id -> list[(date_str, float_value)]]
  Used in tests to inject pre-built data without live API calls.
  If a series_id is in _overrides, live fetch is skipped.
"""

import os
import logging
from datetime import datetime, timezone

from src.liquidity.db.liquidity_schema import create_liquidity_schema
from src.liquidity.db.liquidity_append import append_liquidity_records, get_latest_date
from src.liquidity.fetch.fred import fetch_fred_series
from src.liquidity.fetch.bitcoin import fetch_bitcoin_weekly, fetch_bitcoin_monthly

logger = logging.getLogger(__name__)

# Start date for initial full load
HISTORY_START = "2020-01-01"

# FRED series to fetch: (series_id, frequency_label)
# All fetched from HISTORY_START; frequency is informational (FRED returns native cadence)
FRED_SERIES_IDS = ["WRESBAL", "WALCL", "WDTGAL", "WLRRAL", "BOPGSTB"]

# All 7 series IDs
ALL_SERIES_IDS = FRED_SERIES_IDS + ["BTC_WEEKLY", "BTC_MONTHLY"]


def _filter_new_records(records: list, latest_date: str | None) -> list:
    """
    Filter out records whose date is on or before latest_date.
    If latest_date is None, return all records (initial load).
    """
    if latest_date is None:
        return records
    return [(d, v) for d, v in records if d > latest_date]


def load_liquidity_historical(
    db_path: str,
    fred_api_key: str | None = None,
    _overrides: dict | None = None,
) -> dict:
    """
    Fetch and persist all 7 liquidity series to liquidity_series table.

    Args:
        db_path: Path to the SQLite database file.
        fred_api_key: FRED API key. If None, reads from FRED_KEY env var.
        _overrides: Optional dict for testing -- maps series_id to:
                    list[(date_str, float_value)] -- pre-built records.
                    When provided, skips live fetch for that series.
                    To simulate fetch failure, map series_id -> Exception instance.

    Returns:
        dict mapping series_id -> 'ok: N records inserted' | 'error: <message>'
        All 7 series IDs are present as keys.

    Raises:
        RuntimeError: ONLY if ALL series fail.
    """
    if fred_api_key is None:
        fred_api_key = os.environ.get("FRED_KEY")

    _overrides = _overrides or {}

    fetch_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Ensure schema exists
    create_liquidity_schema(db_path)

    results = {}

    # -------------------------------------------------------------------------
    # Fetch and persist FRED series (AC1, AC2, AC3, AC6)
    # -------------------------------------------------------------------------
    for series_id in FRED_SERIES_IDS:
        try:
            # AC5: determine start date for incremental fetch
            latest_stored = get_latest_date(db_path, series_id)
            fetch_start = latest_stored if latest_stored is not None else HISTORY_START

            if series_id in _overrides:
                override_val = _overrides[series_id]
                # Allow injecting an exception to simulate failure
                if isinstance(override_val, Exception):
                    raise override_val
                raw_records = override_val
            else:
                raw_records = fetch_fred_series(
                    series_id=series_id,
                    observation_start=fetch_start,
                    api_key=fred_api_key,
                )

            # AC5: filter to only new records
            new_records = _filter_new_records(raw_records, latest_stored)

            # Build full (series_id, date, value, fetch_timestamp) tuples
            db_records = [
                (series_id, date_str, val, fetch_timestamp)
                for date_str, val in new_records
            ]

            inserted = append_liquidity_records(db_path, db_records)
            results[series_id] = f"ok: {inserted} records inserted"
            print(f"[liquidity] {series_id}: {inserted} new records inserted")

        except Exception as e:
            # AC6: surface visible error identifying the specific series; do not crash
            error_msg = f"error: {series_id}: {e}"
            results[series_id] = error_msg
            print(f"[liquidity] ERROR {series_id}: {e}")
            logger.error("[liquidity] %s fetch/persist failed: %s", series_id, e)

    # -------------------------------------------------------------------------
    # Fetch and persist Bitcoin prices (AC4, AC7)
    # -------------------------------------------------------------------------
    btc_series = [
        ("BTC_WEEKLY", fetch_bitcoin_weekly),
        ("BTC_MONTHLY", fetch_bitcoin_monthly),
    ]

    for series_id, fetch_fn in btc_series:
        try:
            # AC5: determine start date for incremental fetch
            latest_stored = get_latest_date(db_path, series_id)
            fetch_start = latest_stored if latest_stored is not None else HISTORY_START

            if series_id in _overrides:
                override_val = _overrides[series_id]
                if isinstance(override_val, Exception):
                    raise override_val
                raw_records = override_val
            else:
                raw_records = fetch_fn(start_date=fetch_start)

            # AC5: filter to only new records
            new_records = _filter_new_records(raw_records, latest_stored)

            # Build full (series_id, date, value, fetch_timestamp) tuples
            db_records = [
                (series_id, date_str, val, fetch_timestamp)
                for date_str, val in new_records
            ]

            inserted = append_liquidity_records(db_path, db_records)
            results[series_id] = f"ok: {inserted} records inserted"
            print(f"[liquidity] {series_id}: {inserted} new records inserted")

        except Exception as e:
            # AC7: Bitcoin failure surfaces error but does NOT block FRED fetches
            # (FRED fetches ran first above; this block is isolated)
            error_msg = f"error: {series_id}: {e}"
            results[series_id] = error_msg
            print(f"[liquidity] ERROR {series_id}: {e}")
            logger.error("[liquidity] %s fetch/persist failed: %s", series_id, e)

    # -------------------------------------------------------------------------
    # Ensure all 7 series IDs have a result entry
    # -------------------------------------------------------------------------
    for sid in ALL_SERIES_IDS:
        if sid not in results:
            results[sid] = "error: not attempted"

    # -------------------------------------------------------------------------
    # Raise only if ALL series failed
    # -------------------------------------------------------------------------
    ok_count = sum(1 for v in results.values() if v.startswith("ok"))
    failed = [sid for sid, v in results.items() if not v.startswith("ok")]

    if ok_count == 0:
        raise RuntimeError(
            f"ALL {len(results)} liquidity series failed. "
            f"No data was persisted. First error: {results[ALL_SERIES_IDS[0]]}"
        )

    if failed:
        logger.warning(
            "[liquidity] %d series failed: %s",
            len(failed),
            ", ".join(failed),
        )

    return results
