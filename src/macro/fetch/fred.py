"""
FRED REST API fetch — direct requests (no fredapi library).

Fetches a single FRED series as a pandas Series with DatetimeIndex.
Missing values (FRED uses "." as placeholder) are filtered out.

Environment variable: FRED_API_KEY
"""

import os
import requests
import pandas as pd


FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"


def fetch_fred_series(
    series_id: str,
    observation_start: str = "2000-01-01",
    observation_end: str | None = None,
    api_key: str | None = None,
) -> pd.Series:
    """
    Fetch a FRED series and return it as a pandas Series with DatetimeIndex.

    Args:
        series_id: FRED series identifier (e.g., 'DGS10', 'CPIAUCSL').
        observation_start: Start date in YYYY-MM-DD format.
        observation_end: End date in YYYY-MM-DD format. Defaults to today.
        api_key: FRED API key. If None, reads from FRED_API_KEY env var.

    Returns:
        pd.Series with DatetimeIndex (dates as parsed) and float values.
        "." observations are filtered out.

    Raises:
        RuntimeError: if FRED_API_KEY is not set and no key provided.
        RuntimeError: if the HTTP request fails or the response is invalid.
    """
    if api_key is None:
        api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        raise RuntimeError(
            "FRED_API_KEY environment variable is not set. "
            "Set FRED_API_KEY before calling fetch_fred_series()."
        )

    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": observation_start,
        "sort_order": "asc",
    }
    if observation_end is not None:
        params["observation_end"] = observation_end

    try:
        response = requests.get(FRED_BASE_URL, params=params, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        raise RuntimeError(f"FRED fetch failed for series '{series_id}': {e}") from e

    try:
        data = response.json()
    except Exception as e:
        raise RuntimeError(
            f"FRED response for '{series_id}' is not valid JSON: {e}"
        ) from e

    observations = data.get("observations", [])
    if not observations:
        raise RuntimeError(
            f"FRED returned no observations for series '{series_id}'. "
            f"Response keys: {list(data.keys())}"
        )

    # Filter out missing values (FRED uses "." for missing)
    records = [
        (obs["date"], float(obs["value"]))
        for obs in observations
        if obs.get("value") != "."
    ]

    if not records:
        raise RuntimeError(
            f"FRED series '{series_id}' returned only missing values ('.')."
        )

    dates, values = zip(*records)
    index = pd.to_datetime(list(dates))
    series = pd.Series(list(values), index=index, name=series_id, dtype=float)
    return series
