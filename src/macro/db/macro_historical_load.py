"""
Macro historical data load orchestrator — AC1–AC9.

Fetches all 32 macro indicators and persists them to the macro_indicators table.

Per-indicator error isolation: each indicator is fetched in a try/except block.
If one indicator fails, the others continue and are stored successfully (AC6, AC7).
If ALL indicators fail, raises RuntimeError.

_overrides parameter: dict[indicator_id -> pd.Series | (date, value) tuple]
  - Used in tests to inject pre-built data without live network calls.
  - If an indicator_id is in _overrides, live fetch is skipped.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from src.macro.db.macro_schema import create_macro_schema
from src.macro.db.macro_append import append_macro_records
from src.macro.fetch.fred import fetch_fred_series
from src.macro.fetch.monthly_indicators import (
    fetch_yoy_series, fetch_mom_series, fetch_direct_monthly,
    fetch_breakeven, fetch_ism_services,
    YOY_SERIES, BREAKEVEN_SERIES, DIRECT_MONTHLY_SERIES, MOM_SERIES,
    ISM_SVC_INDICATOR_ID, ISM_SVC_FRED_ID,
)
from src.macro.fetch.yfinance_macro import fetch_yields_currencies_futures
from src.macro.fetch.gdpnow import fetch_gdpnow

logger = logging.getLogger(__name__)

# Minimum row requirements
MIN_DAILY_ROWS = 52
MIN_MONTHLY_ROWS = 12

# All expected indicator IDs (32 total, US_3M_YIELD is intermediate-only)
ALL_INDICATOR_IDS = [
    # Inflation — YoY (monthly)
    "CPI_YOY", "CORE_CPI_YOY", "PCE_YOY", "CORE_PCE_YOY", "PPI_YOY",
    # Breakeven (daily)
    "BREAKEVEN_5Y", "BREAKEVEN_2Y",
    # Yields (daily)
    "US_2Y_YIELD", "US_5Y_YIELD", "US_10Y_YIELD", "US_30Y_YIELD",
    "SPREAD_2S10S", "SPREAD_10Y3M",
    "EFFR",
    # Currencies (daily)
    "DXY", "EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CNH", "USD_CHF",
    # Futures (daily)
    "GOLD_FRONT", "WTI_FRONT", "COPPER_FRONT", "NATGAS_FRONT", "CORN_FRONT",
    # Growth
    "GDPNOW",
    "ISM_MFG_PMI", "ISM_SVC_PMI",
    "NFP", "UNRATE", "RETAIL_SALES_MOM",
]

# Monthly indicator IDs (for min-row check)
MONTHLY_INDICATOR_IDS = {
    "CPI_YOY", "CORE_CPI_YOY", "PCE_YOY", "CORE_PCE_YOY", "PPI_YOY",
    "ISM_MFG_PMI", "ISM_SVC_PMI", "NFP", "UNRATE", "RETAIL_SALES_MOM",
}


def _series_to_records(
    indicator_id: str,
    series: pd.Series,
    fetch_timestamp: str,
    min_rows: int,
) -> list:
    """
    Convert a pd.Series to a list of (indicator_id, date, value, fetch_timestamp) tuples.
    Validates minimum row count.
    """
    series = series.dropna()
    if len(series) < min_rows:
        raise RuntimeError(
            f"{indicator_id}: only {len(series)} rows after dropna — "
            f"need at least {min_rows}."
        )

    records = []
    for dt, val in series.items():
        if hasattr(dt, "strftime"):
            date_str = dt.strftime("%Y-%m-%d")
        else:
            date_str = str(dt)
        records.append((indicator_id, date_str, float(val), fetch_timestamp))
    return records


def load_macro_historical(
    db_path: str,
    fred_api_key: str | None = None,
    _overrides: dict | None = None,
) -> dict:
    """
    Fetch and persist all 32 macro indicators to macro_indicators table.

    Args:
        db_path: Path to the SQLite database file.
        fred_api_key: FRED API key. If None, reads from FRED_API_KEY env var.
        _overrides: Optional dict for testing — maps indicator_id to either:
                    - pd.Series (DatetimeIndex + float values)
                    - tuple (date_str, float_value) for single-point indicators (GDPNow)
                    When provided, skips live fetch for that indicator.

    Returns:
        dict mapping indicator_id -> 'ok' | 'error: <message>'
        All 32 indicator IDs are present as keys.

    Raises:
        RuntimeError: ONLY if ALL indicators fail.
    """
    if fred_api_key is None:
        fred_api_key = os.environ.get("FRED_API_KEY")

    _overrides = _overrides or {}

    fetch_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Ensure schema exists
    create_macro_schema(db_path)

    results = {}
    all_records = []

    # -----------------------------------------------------------------------
    # Step 1: Fetch FRED DGS2 (US_2Y_YIELD) and DGS3MO (3M intermediate)
    #         These are needed by yfinance spread computation too.
    # -----------------------------------------------------------------------
    fred_dgs2_series = None
    fred_dgs3mo_series = None

    if "US_2Y_YIELD" in _overrides:
        override_val = _overrides["US_2Y_YIELD"]
        if isinstance(override_val, pd.Series):
            fred_dgs2_series = override_val
    else:
        try:
            fred_dgs2_series = fetch_fred_series(
                "DGS2", observation_start="2000-01-01", api_key=fred_api_key
            )
        except RuntimeError as e:
            logger.warning("FRED DGS2 fetch failed: %s", e)

    # DGS3MO is intermediate-only (not stored)
    try:
        fred_dgs3mo_series = fetch_fred_series(
            "DGS3MO", observation_start="2000-01-01", api_key=fred_api_key
        )
    except RuntimeError as e:
        logger.warning("FRED DGS3MO fetch failed (intermediate only): %s", e)

    # -----------------------------------------------------------------------
    # Step 2: FRED EFFR
    # -----------------------------------------------------------------------
    if "EFFR" in _overrides:
        effr_series = _overrides["EFFR"] if isinstance(_overrides["EFFR"], pd.Series) else None
    else:
        effr_series = None
        try:
            effr_series = fetch_fred_series(
                "EFFR", observation_start="2000-01-01", api_key=fred_api_key
            )
        except RuntimeError as e:
            logger.warning("FRED EFFR fetch failed: %s", e)

    # -----------------------------------------------------------------------
    # Step 3: yfinance batch (yields, currencies, futures)
    # -----------------------------------------------------------------------
    # Check if all yfinance indicators are in overrides — if so, skip live fetch
    yfinance_indicator_ids = [
        "US_5Y_YIELD", "US_10Y_YIELD", "US_30Y_YIELD",
        "DXY", "EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CNH", "USD_CHF",
        "GOLD_FRONT", "WTI_FRONT", "COPPER_FRONT", "NATGAS_FRONT", "CORN_FRONT",
        "SPREAD_2S10S", "SPREAD_10Y3M",
    ]
    yfinance_results = {}
    all_yfinance_overridden = all(k in _overrides for k in yfinance_indicator_ids)

    if all_yfinance_overridden:
        for iid in yfinance_indicator_ids:
            val = _overrides.get(iid)
            if isinstance(val, pd.Series):
                yfinance_results[iid] = val
    else:
        try:
            yfinance_results = fetch_yields_currencies_futures(
                period="2y",
                fred_dgs2_series=fred_dgs2_series,
                fred_dgs3mo_series=fred_dgs3mo_series,
            )
        except Exception as e:
            logger.warning("yfinance batch fetch failed: %s", e)

        # Apply per-indicator overrides on top of live results
        for iid in yfinance_indicator_ids:
            if iid in _overrides:
                val = _overrides[iid]
                if isinstance(val, pd.Series):
                    yfinance_results[iid] = val

    # -----------------------------------------------------------------------
    # Step 4: Monthly FRED indicators (with YoY/MoM computation)
    # -----------------------------------------------------------------------
    monthly_overrides_complete = all(
        k in _overrides for k in [
            "CPI_YOY", "CORE_CPI_YOY", "PCE_YOY", "CORE_PCE_YOY", "PPI_YOY",
            "BREAKEVEN_5Y", "BREAKEVEN_2Y",
            "ISM_MFG_PMI", "ISM_SVC_PMI", "NFP", "UNRATE", "RETAIL_SALES_MOM",
        ]
    )

    monthly_results = {}

    # YoY series
    for indicator_id, fred_id in YOY_SERIES:
        if indicator_id in _overrides:
            val = _overrides[indicator_id]
            if isinstance(val, pd.Series):
                monthly_results[indicator_id] = val
        elif not monthly_overrides_complete:
            try:
                monthly_results[indicator_id] = fetch_yoy_series(
                    indicator_id, fred_id, api_key=fred_api_key
                )
            except RuntimeError as e:
                logger.warning("%s fetch failed: %s", indicator_id, e)

    # Breakeven (daily)
    for indicator_id, fred_id in BREAKEVEN_SERIES:
        if indicator_id in _overrides:
            val = _overrides[indicator_id]
            if isinstance(val, pd.Series):
                monthly_results[indicator_id] = val
        elif not monthly_overrides_complete:
            try:
                monthly_results[indicator_id] = fetch_breakeven(
                    indicator_id, fred_id, api_key=fred_api_key
                )
            except RuntimeError as e:
                logger.warning("%s fetch failed: %s", indicator_id, e)

    # Direct monthly
    for indicator_id, fred_id in DIRECT_MONTHLY_SERIES:
        if indicator_id in _overrides:
            val = _overrides[indicator_id]
            if isinstance(val, pd.Series):
                monthly_results[indicator_id] = val
        elif not monthly_overrides_complete:
            try:
                monthly_results[indicator_id] = fetch_direct_monthly(
                    indicator_id, fred_id, api_key=fred_api_key
                )
            except RuntimeError as e:
                logger.warning("%s fetch failed: %s", indicator_id, e)

    # MoM series
    for indicator_id, fred_id in MOM_SERIES:
        if indicator_id in _overrides:
            val = _overrides[indicator_id]
            if isinstance(val, pd.Series):
                monthly_results[indicator_id] = val
        elif not monthly_overrides_complete:
            try:
                monthly_results[indicator_id] = fetch_mom_series(
                    indicator_id, fred_id, api_key=fred_api_key
                )
            except RuntimeError as e:
                logger.warning("%s fetch failed: %s", indicator_id, e)

    # ISM Services
    if ISM_SVC_INDICATOR_ID in _overrides:
        val = _overrides[ISM_SVC_INDICATOR_ID]
        if isinstance(val, pd.Series):
            monthly_results[ISM_SVC_INDICATOR_ID] = val
    elif not monthly_overrides_complete:
        try:
            monthly_results[ISM_SVC_INDICATOR_ID] = fetch_ism_services(
                api_key=fred_api_key
            )
        except RuntimeError as e:
            logger.warning("%s fetch failed: %s", ISM_SVC_INDICATOR_ID, e)

    # -----------------------------------------------------------------------
    # Step 5: Per-indicator persistence with error isolation
    # -----------------------------------------------------------------------

    def _persist_series(indicator_id, series, is_monthly=False):
        min_rows = MIN_MONTHLY_ROWS if is_monthly else MIN_DAILY_ROWS
        try:
            recs = _series_to_records(indicator_id, series, fetch_timestamp, min_rows)
            count = append_macro_records(db_path, recs)
            results[indicator_id] = "ok"
            logger.info("%s: %d records inserted", indicator_id, count)
        except Exception as e:
            results[indicator_id] = f"error: {e}"
            logger.error("%s: persistence failed: %s", indicator_id, e)

    # Persist US_2Y_YIELD (FRED DGS2)
    if "US_2Y_YIELD" in _overrides:
        val = _overrides["US_2Y_YIELD"]
        if isinstance(val, pd.Series):
            _persist_series("US_2Y_YIELD", val, is_monthly=False)
        else:
            results["US_2Y_YIELD"] = "error: override is not a pd.Series"
    elif fred_dgs2_series is not None:
        _persist_series("US_2Y_YIELD", fred_dgs2_series, is_monthly=False)
    else:
        results["US_2Y_YIELD"] = "error: FRED DGS2 fetch failed"

    # Persist EFFR
    if "EFFR" in _overrides:
        val = _overrides["EFFR"]
        if isinstance(val, pd.Series):
            _persist_series("EFFR", val, is_monthly=False)
        else:
            results["EFFR"] = "error: override is not a pd.Series"
    elif effr_series is not None:
        _persist_series("EFFR", effr_series, is_monthly=False)
    else:
        results["EFFR"] = "error: FRED EFFR fetch failed"

    # Persist yfinance-based indicators
    for indicator_id in yfinance_indicator_ids:
        if indicator_id in yfinance_results:
            _persist_series(indicator_id, yfinance_results[indicator_id], is_monthly=False)
        elif indicator_id in _overrides:
            val = _overrides[indicator_id]
            if isinstance(val, pd.Series):
                _persist_series(indicator_id, val, is_monthly=False)
            else:
                results[indicator_id] = "error: override is not a pd.Series"
        else:
            results[indicator_id] = f"error: {indicator_id} not available"

    # Persist monthly indicators
    monthly_indicator_ids = [
        id_ for id_, _ in YOY_SERIES
    ] + [
        id_ for id_, _ in BREAKEVEN_SERIES
    ] + [
        id_ for id_, _ in DIRECT_MONTHLY_SERIES
    ] + [
        id_ for id_, _ in MOM_SERIES
    ] + [ISM_SVC_INDICATOR_ID]

    for indicator_id in monthly_indicator_ids:
        is_monthly = indicator_id in MONTHLY_INDICATOR_IDS
        if indicator_id in monthly_results:
            _persist_series(indicator_id, monthly_results[indicator_id], is_monthly=is_monthly)
        else:
            results[indicator_id] = f"error: {indicator_id} not available"

    # -----------------------------------------------------------------------
    # Step 6: GDPNow (isolated — AC7)
    # -----------------------------------------------------------------------
    if "GDPNOW" in _overrides:
        val = _overrides["GDPNOW"]
        if isinstance(val, tuple) and len(val) == 2:
            date_str, estimate = val
            try:
                import math
                fval = float(estimate)
                if math.isnan(fval) or math.isinf(fval):
                    raise ValueError(
                        f"GDPNOW estimate is not a finite number: {estimate}"
                    )
                recs = [("GDPNOW", date_str, fval, fetch_timestamp)]
                append_macro_records(db_path, recs)
                results["GDPNOW"] = "ok"
            except Exception as e:
                results["GDPNOW"] = f"error: {e}"
        elif isinstance(val, pd.Series):
            _persist_series("GDPNOW", val, is_monthly=False)
        else:
            results["GDPNOW"] = "error: GDPNOW override must be tuple (date, value) or pd.Series"
    else:
        try:
            gdpnow_date, gdpnow_val = fetch_gdpnow()
            import math
            fval = float(gdpnow_val)
            if math.isnan(fval) or math.isinf(fval):
                raise RuntimeError(
                    f"GDPNow returned non-finite estimate: {gdpnow_val}"
                )
            recs = [("GDPNOW", gdpnow_date, fval, fetch_timestamp)]
            append_macro_records(db_path, recs)
            results["GDPNOW"] = "ok"
        except RuntimeError as e:
            results["GDPNOW"] = f"error: {e}"
            logger.error("GDPNow fetch failed (isolated): %s", e)

    # -----------------------------------------------------------------------
    # Step 7: Verify not all failed
    # -----------------------------------------------------------------------
    # Ensure all 32 indicator IDs have a result entry
    for iid in ALL_INDICATOR_IDS:
        if iid not in results:
            results[iid] = "error: not attempted"

    failed = [iid for iid, status in results.items() if status.startswith("error")]
    ok_count = len([s for s in results.values() if s == "ok"])

    if ok_count == 0:
        raise RuntimeError(
            f"ALL {len(results)} macro indicators failed. "
            f"No data was persisted. First error: "
            f"{results[ALL_INDICATOR_IDS[0]]}"
        )

    if failed:
        logger.warning(
            "%d indicator(s) failed: %s",
            len(failed),
            ", ".join(failed),
        )

    return results
