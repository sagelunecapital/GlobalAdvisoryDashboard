"""
SPX daily high fetch and EMA computation via yfinance.

Strategy:
  - Download 2 years of ^GSPC data for EMA warm-up
  - Extract the 'High' column as spx_daily_high (DEC-2026-04-18-01)
  - Compute 12-day and 25-day EMA of spx_daily_high
  - Trim to the most recent 1-year window AFTER EMA computation
  - Return DataFrame with columns: date, spx_daily_high, spx_12d_ema, spx_25d_ema
"""

import pandas as pd
import yfinance as yf
from datetime import date, timedelta


def fetch_spx(period: str = "2y") -> pd.DataFrame:
    """
    Fetch SPX daily high prices and compute 12d/25d EMAs.

    Downloads `period` of ^GSPC data (default 2y for EMA warm-up),
    computes EMAs on the full series, then trims to the most recent
    252 trading days (approximately 1 year).

    Returns:
        pd.DataFrame with columns:
            date           (str, YYYY-MM-DD)
            spx_daily_high (float)
            spx_12d_ema    (float)
            spx_25d_ema    (float)

    Raises:
        RuntimeError: if no data is returned from yfinance or required
                      columns are missing.
    """
    raw = yf.download("^GSPC", period=period, interval="1d", auto_adjust=True, progress=False)

    if raw is None or len(raw) == 0:
        raise RuntimeError("yfinance returned no data for ^GSPC")

    # Flatten multi-level columns if present (yfinance >= 0.2 may return MultiIndex)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    if "High" not in raw.columns:
        raise RuntimeError(f"Expected 'High' column not found in ^GSPC data. Columns: {list(raw.columns)}")

    df = pd.DataFrame()
    df["spx_daily_high"] = raw["High"].astype(float)
    df.index = pd.to_datetime(raw.index)

    # Compute EMAs on the full 2-year series for proper warm-up
    df["spx_12d_ema"] = df["spx_daily_high"].ewm(span=12, adjust=False).mean()
    df["spx_25d_ema"] = df["spx_daily_high"].ewm(span=25, adjust=False).mean()

    # Trim to most recent 252 trading days after EMA computation
    df = df.tail(252).copy()

    # Reset index and format date as ISO-8601 string
    df = df.reset_index()
    df = df.rename(columns={"index": "date", "Date": "date"})
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")

    # Drop any rows with NaN (shouldn't occur after warm-up trim, but be safe)
    df = df.dropna(subset=["spx_daily_high", "spx_12d_ema", "spx_25d_ema"])

    return df[["date", "spx_daily_high", "spx_12d_ema", "spx_25d_ema"]].reset_index(drop=True)
