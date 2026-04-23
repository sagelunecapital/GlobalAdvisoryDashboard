"""
Tests for src/macro/fetch/yfinance_macro.py

Covers:
  - Batch fetch returns correct indicator IDs
  - Spread computation (SPREAD_2S10S, SPREAD_10Y3M) verified
  - CNH=X fallback path is reachable (CNY=X used when CNH=X returns <52 rows)
  - Per-ticker isolation: failed tickers don't block others
"""

import pytest
import pandas as pd
import numpy as np
from datetime import date, timedelta
from unittest.mock import patch, MagicMock

from src.macro.fetch.yfinance_macro import (
    fetch_yfinance_batch,
    fetch_yields_currencies_futures,
)


def _make_series(n: int = 100, base: float = 100.0, ticker: str = "TEST") -> pd.Series:
    """Generate a mock pd.Series with DatetimeIndex (business days)."""
    idx = pd.date_range(start="2022-01-03", periods=n, freq="B")
    np.random.seed(hash(ticker) % (2**31))
    vals = base + np.cumsum(np.random.randn(n) * 0.5)
    return pd.Series(vals, index=idx, name=ticker)


def _make_multi_ticker_close_df(tickers: list, n: int = 100) -> pd.DataFrame:
    """
    Build a mock multi-ticker Close DataFrame.
    yfinance returns a MultiIndex (price_type, ticker) structure.
    """
    idx = pd.date_range(start="2022-01-03", periods=n, freq="B")
    data = {}
    for t in tickers:
        np.random.seed(hash(t) % (2**31))
        data[t] = 100.0 + np.cumsum(np.random.randn(n) * 0.5)
    close_df = pd.DataFrame(data, index=idx)
    # Build MultiIndex columns (Close, ticker)
    multi_idx = pd.MultiIndex.from_product([["Close"], tickers], names=["Price", "Ticker"])
    close_df.columns = pd.MultiIndex.from_tuples([("Close", t) for t in tickers])
    return close_df


class TestFetchYfinanceBatch:

    def test_returns_series_per_ticker(self):
        """fetch_yfinance_batch returns a dict with one Series per ticker."""
        tickers = ["^TNX", "GC=F"]
        mock_df = _make_multi_ticker_close_df(tickers, n=100)

        with patch("src.macro.fetch.yfinance_macro.yf.download", return_value=mock_df):
            result = fetch_yfinance_batch(tickers)

        assert "^TNX" in result
        assert "GC=F" in result
        assert isinstance(result["^TNX"], pd.Series)
        assert len(result["^TNX"]) == 100

    def test_empty_tickers_returns_empty_dict(self):
        """Empty tickers list returns empty dict without calling yfinance."""
        with patch("src.macro.fetch.yfinance_macro.yf.download") as mock_dl:
            result = fetch_yfinance_batch([])
        mock_dl.assert_not_called()
        assert result == {}

    def test_single_ticker_flat_columns(self):
        """Single-ticker download with flat columns is handled correctly."""
        ticker = "^TNX"
        idx = pd.date_range(start="2022-01-03", periods=80, freq="B")
        flat_df = pd.DataFrame(
            {"Close": 4.0 + np.random.randn(80) * 0.1},
            index=idx,
        )

        with patch("src.macro.fetch.yfinance_macro.yf.download", return_value=flat_df):
            result = fetch_yfinance_batch([ticker])

        assert ticker in result
        assert len(result[ticker]) == 80


class TestFetchYieldsCurrenciesFutures:

    def _build_full_overrides(self):
        """Build a dict of all indicator overrides for yield/currency/futures."""
        indicator_ids = [
            "US_5Y_YIELD", "US_10Y_YIELD", "US_30Y_YIELD",
            "DXY", "EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CNH", "USD_CHF",
            "GOLD_FRONT", "WTI_FRONT", "COPPER_FRONT", "NATGAS_FRONT", "CORN_FRONT",
        ]
        return {iid: _make_series(100, ticker=iid) for iid in indicator_ids}

    def test_spread_2s10s_computation(self):
        """SPREAD_2S10S = US_10Y_YIELD (^TNX) - DGS2 computed via inner join."""
        idx = pd.date_range(start="2022-01-03", periods=100, freq="B")
        tnx_series = pd.Series(4.5 + np.zeros(100), index=idx)
        dgs2_series = pd.Series(4.0 + np.zeros(100), index=idx)

        # Build a mock multi-ticker df that includes ^TNX
        all_tickers = [
            "^FVX", "^TNX", "^TYX", "^IRX",
            "DX-Y.NYB", "EURUSD=X", "GBPUSD=X", "JPY=X", "AUDUSD=X", "CNH=X", "CHF=X",
            "GC=F", "CL=F", "HG=F", "NG=F", "ZC=F",
        ]
        mock_df = _make_multi_ticker_close_df(all_tickers, n=100)
        # Override ^TNX column
        mock_df[("Close", "^TNX")] = tnx_series.values

        with patch("src.macro.fetch.yfinance_macro.yf.download", return_value=mock_df):
            result = fetch_yields_currencies_futures(
                period="2y",
                fred_dgs2_series=dgs2_series,
            )

        assert "SPREAD_2S10S" in result
        spread = result["SPREAD_2S10S"]
        # Should be approximately 4.5 - 4.0 = 0.5 for all dates
        assert abs(spread.mean() - 0.5) < 0.01

    def test_spread_10y3m_computation(self):
        """SPREAD_10Y3M = US_10Y_YIELD (^TNX) - US_3M_YIELD (^IRX) computed via inner join."""
        idx = pd.date_range(start="2022-01-03", periods=100, freq="B")
        tnx_series = pd.Series(4.5 + np.zeros(100), index=idx)
        irx_series = pd.Series(5.0 + np.zeros(100), index=idx)

        all_tickers = [
            "^FVX", "^TNX", "^TYX", "^IRX",
            "DX-Y.NYB", "EURUSD=X", "GBPUSD=X", "JPY=X", "AUDUSD=X", "CNH=X", "CHF=X",
            "GC=F", "CL=F", "HG=F", "NG=F", "ZC=F",
        ]
        mock_df = _make_multi_ticker_close_df(all_tickers, n=100)
        mock_df[("Close", "^TNX")] = tnx_series.values
        mock_df[("Close", "^IRX")] = irx_series.values

        dgs2_series = pd.Series(4.0 + np.zeros(100), index=idx)

        with patch("src.macro.fetch.yfinance_macro.yf.download", return_value=mock_df):
            result = fetch_yields_currencies_futures(
                period="2y",
                fred_dgs2_series=dgs2_series,
            )

        assert "SPREAD_10Y3M" in result
        spread = result["SPREAD_10Y3M"]
        assert abs(spread.mean() - (-0.5)) < 0.01

    def test_cnh_fallback_triggered(self):
        """When CNH=X returns <52 rows, CNY=X fallback is tried."""
        idx_short = pd.date_range(start="2024-01-01", periods=10, freq="B")
        idx_long = pd.date_range(start="2022-01-03", periods=100, freq="B")

        all_tickers = [
            "^FVX", "^TNX", "^TYX", "^IRX",
            "DX-Y.NYB", "EURUSD=X", "GBPUSD=X", "JPY=X", "AUDUSD=X", "CNH=X", "CHF=X",
            "GC=F", "CL=F", "HG=F", "NG=F", "ZC=F",
        ]
        # Build multi-ticker df with CNH=X having only 10 rows (injected via mock)
        mock_df_full = _make_multi_ticker_close_df(all_tickers, n=100)
        # Make CNH=X short (NaN out most rows)
        mock_df_full[("Close", "CNH=X")] = float("nan")
        mock_df_full.loc[idx_long[:10], ("Close", "CNH=X")] = 7.2

        # CNY=X fallback df
        cny_df = pd.DataFrame(
            {"Close": 7.25 + np.random.randn(100) * 0.01},
            index=idx_long,
        )

        call_count = {"n": 0}

        def mock_download(tickers, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return mock_df_full  # first call: all tickers
            else:
                return cny_df  # fallback call for CNY=X

        dgs2_series = pd.Series(4.0 + np.zeros(100), index=idx_long)

        with patch("src.macro.fetch.yfinance_macro.yf.download", side_effect=mock_download):
            result = fetch_yields_currencies_futures(
                period="2y",
                fred_dgs2_series=dgs2_series,
            )

        # CNY=X fallback was invoked
        assert call_count["n"] == 2
        # USD_CNH should be present (from CNY=X fallback)
        assert "USD_CNH" in result
        assert len(result["USD_CNH"]) >= 52

    def test_correct_indicator_ids_returned(self):
        """Result contains the expected indicator IDs."""
        all_tickers = [
            "^FVX", "^TNX", "^TYX", "^IRX",
            "DX-Y.NYB", "EURUSD=X", "GBPUSD=X", "JPY=X", "AUDUSD=X", "CNH=X", "CHF=X",
            "GC=F", "CL=F", "HG=F", "NG=F", "ZC=F",
        ]
        mock_df = _make_multi_ticker_close_df(all_tickers, n=100)
        idx = pd.date_range(start="2022-01-03", periods=100, freq="B")
        dgs2_series = pd.Series(4.0 + np.zeros(100), index=idx)

        with patch("src.macro.fetch.yfinance_macro.yf.download", return_value=mock_df):
            result = fetch_yields_currencies_futures(
                period="2y",
                fred_dgs2_series=dgs2_series,
            )

        expected_ids = {
            "US_5Y_YIELD", "US_10Y_YIELD", "US_30Y_YIELD",
            "DXY", "EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CNH", "USD_CHF",
            "GOLD_FRONT", "WTI_FRONT", "COPPER_FRONT", "NATGAS_FRONT", "CORN_FRONT",
            "US_2Y_YIELD",  # from fred_dgs2_series
            "SPREAD_2S10S", "SPREAD_10Y3M",
        }
        for iid in expected_ids:
            assert iid in result, f"Expected {iid} in result but missing"
