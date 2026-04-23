"""
FRED monthly indicators — inflation + growth series.

Fetches FRED monthly series and computes:
  - YoY % change: ((t / t-12) - 1) * 100 for CPI, Core CPI, PCE, Core PCE, PPI
  - MoM % change: ((t / t-1) - 1) * 100 for Retail Sales
  - Direct values: ISM Manufacturing PMI, ISM Services PMI, NFP, Unemployment Rate

Month-end dates: FRED first-of-month dates are converted to month-end via
pd.tseries.offsets.MonthEnd(0).

AC2: stores most recently released value — not forecasted/interpolated.
"""

import logging
import pandas as pd

from src.macro.fetch.fred import fetch_fred_series

logger = logging.getLogger(__name__)


# --- FRED series mappings ---

# YoY inflation series: (indicator_id, fred_series_id)
YOY_SERIES = [
    ("CPI_YOY",      "CPIAUCSL"),
    ("CORE_CPI_YOY", "CPILFESL"),
    ("PCE_YOY",      "PCEPI"),
    ("CORE_PCE_YOY", "PCEPILFE"),
    ("PPI_YOY",      "PPIACO"),
]

# Breakeven inflation series (daily, value direct)
BREAKEVEN_SERIES = [
    ("BREAKEVEN_5Y", "T5YIE"),
    ("BREAKEVEN_2Y", "T2YIE"),
]

# Direct monthly series (no transformation needed)
DIRECT_MONTHLY_SERIES = [
    ("ISM_MFG_PMI",  "NAPM"),
    ("UNRATE",       "UNRATE"),
    ("NFP",          "PAYEMS"),
]

# MoM series
MOM_SERIES = [
    ("RETAIL_SALES_MOM", "RSAFS"),
]

# ISM Services — special guard
ISM_SVC_FRED_ID = "NMFCI"
ISM_SVC_INDICATOR_ID = "ISM_SVC_PMI"


def _to_month_end(series: pd.Series) -> pd.Series:
    """Convert DatetimeIndex to month-end dates."""
    series = series.copy()
    series.index = series.index + pd.tseries.offsets.MonthEnd(0)
    return series


def fetch_yoy_series(
    indicator_id: str,
    fred_series_id: str,
    observation_start: str = "2000-01-01",
    api_key: str | None = None,
) -> pd.Series:
    """
    Fetch a FRED monthly level series and compute YoY % change.
    Converts dates to month-end.

    Returns:
        pd.Series with month-end DatetimeIndex and YoY % values.
        At least 12 observations after computation.

    Raises:
        RuntimeError: on fetch failure or insufficient data.
    """
    raw = fetch_fred_series(
        fred_series_id,
        observation_start=observation_start,
        api_key=api_key,
    )
    raw = _to_month_end(raw)

    # YoY: ((t / t-12) - 1) * 100
    yoy = ((raw / raw.shift(12)) - 1) * 100
    yoy = yoy.dropna()

    if len(yoy) < 12:
        raise RuntimeError(
            f"{indicator_id} ({fred_series_id}): only {len(yoy)} observations "
            f"after YoY computation — need at least 12."
        )

    yoy.name = indicator_id
    return yoy


def fetch_mom_series(
    indicator_id: str,
    fred_series_id: str,
    observation_start: str = "2000-01-01",
    api_key: str | None = None,
) -> pd.Series:
    """
    Fetch a FRED monthly level series and compute MoM % change.
    Converts dates to month-end.

    Returns:
        pd.Series with month-end DatetimeIndex and MoM % values.

    Raises:
        RuntimeError: on fetch failure or insufficient data.
    """
    raw = fetch_fred_series(
        fred_series_id,
        observation_start=observation_start,
        api_key=api_key,
    )
    raw = _to_month_end(raw)

    # MoM: ((t / t-1) - 1) * 100
    mom = ((raw / raw.shift(1)) - 1) * 100
    mom = mom.dropna()

    if len(mom) < 12:
        raise RuntimeError(
            f"{indicator_id} ({fred_series_id}): only {len(mom)} observations "
            f"after MoM computation — need at least 12."
        )

    mom.name = indicator_id
    return mom


def fetch_direct_monthly(
    indicator_id: str,
    fred_series_id: str,
    observation_start: str = "2000-01-01",
    api_key: str | None = None,
) -> pd.Series:
    """
    Fetch a FRED monthly series and return values directly (no transformation).
    Converts dates to month-end.

    Returns:
        pd.Series with month-end DatetimeIndex and float values.

    Raises:
        RuntimeError: on fetch failure or insufficient data.
    """
    raw = fetch_fred_series(
        fred_series_id,
        observation_start=observation_start,
        api_key=api_key,
    )
    raw = _to_month_end(raw)

    if len(raw) < 12:
        raise RuntimeError(
            f"{indicator_id} ({fred_series_id}): only {len(raw)} observations — "
            f"need at least 12."
        )

    raw.name = indicator_id
    return raw


def fetch_breakeven(
    indicator_id: str,
    fred_series_id: str,
    observation_start: str = "2000-01-01",
    api_key: str | None = None,
) -> pd.Series:
    """
    Fetch a FRED daily breakeven inflation series. No transformation.

    Returns:
        pd.Series with DatetimeIndex and float values.

    Raises:
        RuntimeError: on fetch failure or insufficient data.
    """
    raw = fetch_fred_series(
        fred_series_id,
        observation_start=observation_start,
        api_key=api_key,
    )

    if len(raw) < 52:
        raise RuntimeError(
            f"{indicator_id} ({fred_series_id}): only {len(raw)} observations — "
            f"need at least 52."
        )

    raw.name = indicator_id
    return raw


def fetch_ism_services(
    observation_start: str = "2000-01-01",
    api_key: str | None = None,
) -> pd.Series:
    """
    Fetch ISM Services PMI from FRED series NMFCI.

    Raises:
        RuntimeError: with message "ISM Services PMI: NMFCI returned no data.
                      Check FRED for current series ID." if series is empty
                      or returns an HTTP error.
    """
    try:
        raw = fetch_fred_series(
            ISM_SVC_FRED_ID,
            observation_start=observation_start,
            api_key=api_key,
        )
    except RuntimeError as e:
        raise RuntimeError(
            "ISM Services PMI: NMFCI returned no data. "
            "Check FRED for current series ID."
        ) from e

    if len(raw) == 0:
        raise RuntimeError(
            "ISM Services PMI: NMFCI returned no data. "
            "Check FRED for current series ID."
        )

    raw = _to_month_end(raw)
    raw.name = ISM_SVC_INDICATOR_ID
    return raw


def fetch_all_monthly(
    observation_start: str = "2000-01-01",
    api_key: str | None = None,
) -> dict:
    """
    Fetch all monthly FRED indicators.

    Returns:
        dict mapping indicator_id -> pd.Series.
        Indicators that fail are raised — caller handles per-indicator isolation.
    """
    result = {}

    # YoY inflation
    for indicator_id, fred_id in YOY_SERIES:
        result[indicator_id] = fetch_yoy_series(indicator_id, fred_id, observation_start, api_key)

    # Breakeven (daily, direct)
    for indicator_id, fred_id in BREAKEVEN_SERIES:
        result[indicator_id] = fetch_breakeven(indicator_id, fred_id, observation_start, api_key)

    # Direct monthly
    for indicator_id, fred_id in DIRECT_MONTHLY_SERIES:
        result[indicator_id] = fetch_direct_monthly(indicator_id, fred_id, observation_start, api_key)

    # MoM
    for indicator_id, fred_id in MOM_SERIES:
        result[indicator_id] = fetch_mom_series(indicator_id, fred_id, observation_start, api_key)

    # ISM Services (special guard)
    result[ISM_SVC_INDICATOR_ID] = fetch_ism_services(observation_start, api_key)

    return result
