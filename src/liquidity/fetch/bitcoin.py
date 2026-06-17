"""
Bitcoin price fetcher using yfinance (ticker BTC-USD).

Fetches BTC-USD at weekly and monthly frequency from a given start date.
Returns list of (date_str, value) tuples for each frequency.

Series IDs used:
  BTC_WEEKLY  -- weekly close prices (AC4)
  BTC_MONTHLY -- monthly close prices (AC4)

yfinance is an established project dependency (already in requirements.txt).
"""

from datetime import datetime, date
import pandas as pd
import yfinance as yf


BTC_TICKER = "BTC-USD"


def _resample_to_weekly(df: pd.DataFrame) -> list:
    """
    Resample a daily OHLCV DataFrame to weekly (week-end) close prices.
    Returns list of (date_str, float_value) tuples.
    """
    if df.empty:
        return []

    # Use 'Close' column (or 'Adj Close' if present)
    close_col = "Close" if "Close" in df.columns else df.columns[0]
    series = df[close_col].copy()

    # Ensure DatetimeIndex
    if not isinstance(series.index, pd.DatetimeIndex):
        series.index = pd.to_datetime(series.index)

    # Resample to week-end Friday
    weekly = series.resample("W-FRI").last().dropna()

    result = []
    for dt, val in weekly.items():
        result.append((dt.strftime("%Y-%m-%d"), float(val)))
    return result


def _resample_to_monthly(df: pd.DataFrame) -> list:
    """
    Resample a daily OHLCV DataFrame to month-end close prices.
    Returns list of (date_str, float_value) tuples.
    """
    if df.empty:
        return []

    close_col = "Close" if "Close" in df.columns else df.columns[0]
    series = df[close_col].copy()

    if not isinstance(series.index, pd.DatetimeIndex):
        series.index = pd.to_datetime(series.index)

    # Resample to month-end
    monthly = series.resample("ME").last().dropna()

    result = []
    for dt, val in monthly.items():
        result.append((dt.strftime("%Y-%m-%d"), float(val)))
    return result


def fetch_bitcoin_weekly(
    start_date: str = "2020-01-01",
    end_date: str | None = None,
) -> list:
    """
    Fetch BTC-USD weekly close prices from start_date to end_date.

    Args:
        start_date: Start date in YYYY-MM-DD format.
        end_date: End date in YYYY-MM-DD format. Defaults to today.

    Returns:
        List of (date_str, float_value) tuples at weekly (Fri) frequency.

    Raises:
        RuntimeError: if yfinance returns empty data or download fails.
    """
    if end_date is None:
        end_date = date.today().strftime("%Y-%m-%d")

    try:
        ticker = yf.Ticker(BTC_TICKER)
        df = ticker.history(start=start_date, end=end_date, interval="1d", auto_adjust=True)
    except Exception as e:
        raise RuntimeError(
            f"BTC_WEEKLY: yfinance download failed for {BTC_TICKER}: {e}"
        ) from e

    if df is None or df.empty:
        raise RuntimeError(
            f"BTC_WEEKLY: yfinance returned empty data for {BTC_TICKER} "
            f"(start={start_date}, end={end_date})."
        )

    records = _resample_to_weekly(df)
    if not records:
        raise RuntimeError(
            f"BTC_WEEKLY: no weekly records produced from {BTC_TICKER} data."
        )
    return records


def fetch_bitcoin_monthly(
    start_date: str = "2020-01-01",
    end_date: str | None = None,
) -> list:
    """
    Fetch BTC-USD monthly close prices from start_date to end_date.

    Args:
        start_date: Start date in YYYY-MM-DD format.
        end_date: End date in YYYY-MM-DD format. Defaults to today.

    Returns:
        List of (date_str, float_value) tuples at monthly (month-end) frequency.

    Raises:
        RuntimeError: if yfinance returns empty data or download fails.
    """
    if end_date is None:
        end_date = date.today().strftime("%Y-%m-%d")

    try:
        ticker = yf.Ticker(BTC_TICKER)
        df = ticker.history(start=start_date, end=end_date, interval="1d", auto_adjust=True)
    except Exception as e:
        raise RuntimeError(
            f"BTC_MONTHLY: yfinance download failed for {BTC_TICKER}: {e}"
        ) from e

    if df is None or df.empty:
        raise RuntimeError(
            f"BTC_MONTHLY: yfinance returned empty data for {BTC_TICKER} "
            f"(start={start_date}, end={end_date})."
        )

    records = _resample_to_monthly(df)
    if not records:
        raise RuntimeError(
            f"BTC_MONTHLY: no monthly records produced from {BTC_TICKER} data."
        )
    return records
