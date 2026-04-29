"""
Shared pytest fixtures for E01S06 tests.

Fixtures:
  tmp_db          — temporary SQLite DB path (unique per test)
  sample_spx_df   — mock DataFrame with 400 rows of SPX data (covers 2y fetch + 1y trim)
  sample_mmth_series — mock MMTH Series with DatetimeIndex (400 trading days)
"""

import pandas as pd
import numpy as np
import pytest
from datetime import date, timedelta


def _generate_trading_dates(n: int, end: date = None) -> list:
    """Generate n business days ending on `end` (default: today)."""
    if end is None:
        end = date(2025, 4, 18)  # Fixed date for reproducibility
    dates = []
    current = end
    while len(dates) < n:
        if current.weekday() < 5:  # Mon-Fri
            dates.append(current)
        current -= timedelta(days=1)
    return list(reversed(dates))


@pytest.fixture
def tmp_db(tmp_path):
    """
    Provide a path to a temporary SQLite database file.
    The file does not exist yet — tests create it via schema/load/append functions.
    """
    return str(tmp_path / "test_indicators.db")


@pytest.fixture
def sample_spx_df():
    """
    Mock SPX DataFrame with 400 trading-day rows.
    Covers the 2-year fetch window (with warm-up) needed by historical_load.
    Columns: date (str YYYY-MM-DD), spx_daily_high, spx_12d_ema, spx_25d_ema.
    """
    n = 400
    trading_dates = _generate_trading_dates(n)
    np.random.seed(42)
    # Simulate realistic SPX prices around 4500–5500
    base = 5000.0
    prices = base + np.cumsum(np.random.randn(n) * 15)
    prices = np.abs(prices)  # ensure positive

    df = pd.DataFrame({
        "date": [d.strftime("%Y-%m-%d") for d in trading_dates],
        "spx_daily_high": prices,
        "spx_12d_ema": prices * 0.998,
        "spx_25d_ema": prices * 0.995,
    })
    return df


@pytest.fixture
def sample_mmth_series():
    """
    Mock MMTH Series with DatetimeIndex, 400 trading-day rows.
    Values are floats in [0, 100] representing % stocks above 200d MA.
    """
    n = 400
    trading_dates = _generate_trading_dates(n)
    np.random.seed(99)
    values = 50.0 + np.cumsum(np.random.randn(n) * 0.5)
    values = np.clip(values, 0, 100)

    idx = pd.to_datetime([d.isoformat() for d in trading_dates])
    series = pd.Series(values, index=idx, name="mmth", dtype=float)
    return series
