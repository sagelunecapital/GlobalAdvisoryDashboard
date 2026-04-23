"""
Tests for src/macro/fetch/monthly_indicators.py

Covers:
  - YoY computed correctly: (110/100 - 1) * 100 = 10.0%
  - MoM computed correctly
  - Month-end dates enforced (first-of-month -> month-end)
  - NMFCI guard: RuntimeError when NMFCI returns no data
"""

import pytest
import pandas as pd
import numpy as np
from datetime import date
from unittest.mock import patch, MagicMock

from src.macro.fetch.monthly_indicators import (
    fetch_yoy_series,
    fetch_mom_series,
    fetch_direct_monthly,
    fetch_ism_services,
    fetch_breakeven,
)


def _make_monthly_series(n_months: int = 36, base_value: float = 100.0, start: str = "2020-01-01") -> pd.Series:
    """Generate a pd.Series with monthly DatetimeIndex (first-of-month dates)."""
    idx = pd.date_range(start=start, periods=n_months, freq="MS")
    values = base_value + np.arange(n_months, dtype=float)
    return pd.Series(values, index=idx, name="test_series")


def _make_daily_series(n: int = 300, base_value: float = 2.5, start: str = "2020-01-01") -> pd.Series:
    """Generate a pd.Series with daily DatetimeIndex."""
    idx = pd.date_range(start=start, periods=n, freq="B")  # business days
    values = base_value + np.random.rand(n) * 0.1
    return pd.Series(values, index=idx, name="test_daily")


class TestYoYComputation:

    def test_yoy_10_percent(self):
        """YoY: value(t) = 110, value(t-12) = 100 → 10.0% exactly."""
        # 25 months: first 13 base, then 13 incremented to 110
        idx = pd.date_range(start="2022-01-01", periods=25, freq="MS")
        values = [100.0] * 13 + [110.0] * 12
        series = pd.Series(values, index=idx)

        with patch("src.macro.fetch.monthly_indicators.fetch_fred_series", return_value=series):
            result = fetch_yoy_series("CPI_YOY", "CPIAUCSL", api_key="test-key")

        # The most recent 12 observations should show 10.0% YoY
        assert isinstance(result, pd.Series)
        # Last value: 110 / 100 - 1 = 0.10 → 10.0%
        last_val = result.iloc[-1]
        assert abs(last_val - 10.0) < 1e-6, f"Expected 10.0%, got {last_val}"

    def test_yoy_result_length(self):
        """YoY result has correct length (n - 12 after shift)."""
        n = 36
        series = _make_monthly_series(n_months=n)

        with patch("src.macro.fetch.monthly_indicators.fetch_fred_series", return_value=series):
            result = fetch_yoy_series("CPI_YOY", "CPIAUCSL", api_key="test-key")

        assert len(result) == n - 12

    def test_month_end_dates(self):
        """FRED first-of-month dates are converted to month-end."""
        series = _make_monthly_series(n_months=24)
        # Input has first-of-month dates
        assert series.index[0].day == 1

        with patch("src.macro.fetch.monthly_indicators.fetch_fred_series", return_value=series):
            result = fetch_yoy_series("CPI_YOY", "CPIAUCSL", api_key="test-key")

        # All result dates should be month-end
        for dt in result.index:
            next_day = dt + pd.Timedelta(days=1)
            assert next_day.month != dt.month, f"Date {dt} is not month-end"

    def test_yoy_insufficient_data_raises(self):
        """RuntimeError raised if fewer than 12 observations after YoY."""
        # Only 13 months: after shift(12) + dropna → 1 observation
        # But we need ≥12 — should fail
        series = _make_monthly_series(n_months=13)

        with patch("src.macro.fetch.monthly_indicators.fetch_fred_series", return_value=series):
            with pytest.raises(RuntimeError, match="CPI_YOY"):
                fetch_yoy_series("CPI_YOY", "CPIAUCSL", api_key="test-key")


class TestMoMComputation:

    def test_mom_computation(self):
        """MoM: value(t) = 110, value(t-1) = 100 → 10.0%."""
        idx = pd.date_range(start="2022-01-01", periods=15, freq="MS")
        values = [100.0] + [110.0] * 14
        series = pd.Series(values, index=idx)

        with patch("src.macro.fetch.monthly_indicators.fetch_fred_series", return_value=series):
            result = fetch_mom_series("RETAIL_SALES_MOM", "RSAFS", api_key="test-key")

        assert isinstance(result, pd.Series)
        # First valid MoM: 110/100 - 1 = 10.0%
        assert abs(result.iloc[0] - 10.0) < 1e-6

    def test_mom_month_end_dates(self):
        """MoM result dates are month-end."""
        series = _make_monthly_series(n_months=24)

        with patch("src.macro.fetch.monthly_indicators.fetch_fred_series", return_value=series):
            result = fetch_mom_series("RETAIL_SALES_MOM", "RSAFS", api_key="test-key")

        for dt in result.index:
            next_day = dt + pd.Timedelta(days=1)
            assert next_day.month != dt.month, f"Date {dt} is not month-end"


class TestDirectMonthly:

    def test_direct_monthly_passthrough(self):
        """Direct monthly series is returned as-is (no transformation) with month-end dates."""
        series = _make_monthly_series(n_months=24, base_value=50.0)

        with patch("src.macro.fetch.monthly_indicators.fetch_fred_series", return_value=series):
            result = fetch_direct_monthly("ISM_MFG_PMI", "NAPM", api_key="test-key")

        assert isinstance(result, pd.Series)
        assert len(result) == 24
        # Values unchanged
        assert abs(result.iloc[0] - 50.0) < 1e-6

    def test_direct_monthly_month_end(self):
        """Direct monthly series has month-end dates."""
        series = _make_monthly_series(n_months=24)

        with patch("src.macro.fetch.monthly_indicators.fetch_fred_series", return_value=series):
            result = fetch_direct_monthly("UNRATE", "UNRATE", api_key="test-key")

        for dt in result.index:
            next_day = dt + pd.Timedelta(days=1)
            assert next_day.month != dt.month


class TestISMServicesGuard:

    def test_ism_svc_nmfci_no_data_raises(self):
        """RuntimeError with exact guard message when NMFCI returns no data."""
        with patch(
            "src.macro.fetch.monthly_indicators.fetch_fred_series",
            side_effect=RuntimeError("FRED returned no observations for series 'NMFCI'"),
        ):
            with pytest.raises(RuntimeError) as exc_info:
                fetch_ism_services(api_key="test-key")

        assert "NMFCI" in str(exc_info.value)
        assert "Check FRED for current series ID" in str(exc_info.value)

    def test_ism_svc_valid_data_returned(self):
        """Valid NMFCI data is returned as ISM_SVC_PMI series."""
        series = _make_monthly_series(n_months=24, base_value=52.0)

        with patch("src.macro.fetch.monthly_indicators.fetch_fred_series", return_value=series):
            result = fetch_ism_services(api_key="test-key")

        assert isinstance(result, pd.Series)
        assert result.name == "ISM_SVC_PMI"
        assert len(result) == 24


class TestBreakevenFetch:

    def test_breakeven_daily_no_transform(self):
        """Daily breakeven series returned with original values and dates."""
        np.random.seed(7)
        series = _make_daily_series(n=300, base_value=2.5)

        with patch("src.macro.fetch.monthly_indicators.fetch_fred_series", return_value=series):
            result = fetch_breakeven("BREAKEVEN_5Y", "T5YIE", api_key="test-key")

        assert isinstance(result, pd.Series)
        assert len(result) == 300

    def test_breakeven_insufficient_raises(self):
        """RuntimeError if daily series has <52 observations."""
        series = _make_daily_series(n=30)

        with patch("src.macro.fetch.monthly_indicators.fetch_fred_series", return_value=series):
            with pytest.raises(RuntimeError, match="BREAKEVEN_5Y"):
                fetch_breakeven("BREAKEVEN_5Y", "T5YIE", api_key="test-key")
