"""
MMTH fetch: yfinance primary, EODData fallback.

MMTH DATA SOURCE DECISION (verified 2026-04-22):
  - yfinance primary (^MMTH): UNAVAILABLE.
    yfinance returns HTTP 404 for ^MMTH ("Quote not found for symbol: ^MMTH").
    The ticker appears to be delisted or not supported by Yahoo Finance.
  - Fallback: EODData API (eodhistoricaldata.com).
    EODData provides MMTH (% NYSE stocks above 200-day MA) via REST API.
    Requires an API key in the environment variable EODDATA_API_KEY.
    If the key is not set, fetch_mmth() raises a RuntimeError with clear instructions.

To configure EODData:
  1. Register at https://eodhistoricaldata.com/ (free tier available)
  2. Set environment variable: EODDATA_API_KEY=<your_key>
  3. Re-run the historical load.
"""

import os
import requests
import pandas as pd
from datetime import date, timedelta


EODDATA_API_KEY_ENV = "EODDATA_API_KEY"
EODDATA_BASE_URL = "https://eodhistoricaldata.com/api/eod/MMTH.INDX"


def fetch_mmth_yfinance(period: str = "2y") -> pd.Series:
    """
    Attempt to fetch MMTH via yfinance.

    NOTE: As of 2026-04-22, ^MMTH is NOT available on Yahoo Finance.
    This function is retained for future compatibility but will raise
    RuntimeError with the current state of Yahoo Finance's data.

    Returns:
        pd.Series with DatetimeIndex and float MMTH values (252+ entries)

    Raises:
        RuntimeError: always, since ^MMTH is unavailable on Yahoo Finance.
    """
    import yfinance as yf
    raw = yf.download("^MMTH", period=period, interval="1d", auto_adjust=True, progress=False)

    if raw is None or len(raw) == 0:
        raise RuntimeError(
            "yfinance: ^MMTH is not available (HTTP 404 from Yahoo Finance). "
            "Falling back to EODData. Set EODDATA_API_KEY to enable."
        )

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    series = raw["Close"].dropna().astype(float)
    series.index = pd.to_datetime(series.index)
    return series


def fetch_mmth_eoddata(period_days: int = 730) -> pd.Series:
    """
    Fetch MMTH (% NYSE stocks above 200-day MA) from EODHistorical Data API.

    Requires environment variable EODDATA_API_KEY to be set.

    Args:
        period_days: Number of calendar days of history to request (default 730 ~ 2 years)

    Returns:
        pd.Series with DatetimeIndex (daily) and float MMTH values (252+ entries)

    Raises:
        RuntimeError: if EODDATA_API_KEY is not set, or if the API returns
                      insufficient data.
        requests.HTTPError: if the API request fails.
    """
    api_key = os.environ.get(EODDATA_API_KEY_ENV)
    if not api_key:
        raise RuntimeError(
            f"MMTH data source unavailable: yfinance does not provide ^MMTH data. "
            f"EODData fallback requires the environment variable '{EODDATA_API_KEY_ENV}' to be set. "
            f"Register at https://eodhistoricaldata.com/ (free tier available), "
            f"then set {EODDATA_API_KEY_ENV}=<your_key> and retry."
        )

    from_date = (date.today() - timedelta(days=period_days)).isoformat()
    to_date = date.today().isoformat()

    params = {
        "api_token": api_key,
        "from": from_date,
        "to": to_date,
        "fmt": "json",
        "period": "d",
    }

    response = requests.get(EODDATA_BASE_URL, params=params, timeout=30)
    response.raise_for_status()

    data = response.json()
    if not data or not isinstance(data, list):
        raise RuntimeError(
            f"EODData returned unexpected response format for MMTH.INDX: {type(data)}"
        )

    records = [(item["date"], float(item["close"])) for item in data if "date" in item and "close" in item]
    if len(records) < 252:
        raise RuntimeError(
            f"EODData returned only {len(records)} records for MMTH — need at least 252 trading days. "
            f"Check your API key and date range."
        )

    idx = pd.to_datetime([r[0] for r in records])
    values = [r[1] for r in records]
    series = pd.Series(values, index=idx, name="mmth", dtype=float)
    series = series.sort_index()
    return series


def fetch_mmth(period: str = "2y") -> pd.Series:
    """
    Fetch MMTH with automatic fallback.

    Tries yfinance first; falls back to EODData if yfinance is unavailable.
    As of 2026-04-22, yfinance does NOT provide ^MMTH — EODData fallback
    is the active code path.

    Returns:
        pd.Series with DatetimeIndex and float MMTH values

    Raises:
        RuntimeError: if both yfinance and EODData are unavailable.
    """
    try:
        series = fetch_mmth_yfinance(period=period)
        if len(series) >= 252:
            return series
        # Insufficient data — fall through to EODData
        raise RuntimeError(f"yfinance returned only {len(series)} rows for ^MMTH — insufficient")
    except RuntimeError as yf_error:
        # yfinance failed — attempt EODData
        try:
            return fetch_mmth_eoddata(period_days=730)
        except RuntimeError as eod_error:
            # Both failed — surface a combined error
            raise RuntimeError(
                f"MMTH fetch failed on both yfinance and EODData.\n"
                f"  yfinance error: {yf_error}\n"
                f"  EODData error: {eod_error}"
            ) from eod_error
