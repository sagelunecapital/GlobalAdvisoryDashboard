"""
FRED REST API fetch for liquidity series -- direct requests (no fredapi library).

Fetches a single FRED series as a list of (date, value) tuples.
Missing values (FRED uses "." as placeholder) are filtered out.

Environment variable: FRED_KEY
  (Note: this module uses FRED_KEY, distinct from the macro module's FRED_API_KEY,
  to allow independent configuration per module.)

Series fetched by historical_load:
  Weekly (observation_start 2020-01-01):
    WRESBAL  -- Reserve Balances with Federal Reserve Banks (AC1)
    WALCL    -- Fed total assets (AC2)
    WDTGAL   -- Deposits at Federal Reserve (AC2)
    WLRRAL   -- Reverse repurchase agreements (AC2)
  Monthly (observation_start 2020-01-01):
    BOPGSTB  -- US trade balance of goods and services (AC3)
"""

import os
import requests


FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"


# Series IDs and their frequencies for liquidity module
WEEKLY_FRED_SERIES = ["WRESBAL", "WALCL", "WDTGAL", "WLRRAL"]
MONTHLY_FRED_SERIES = ["BOPGSTB"]


def fetch_fred_series(
    series_id: str,
    observation_start: str = "2020-01-01",
    observation_end: str | None = None,
    api_key: str | None = None,
) -> list:
    """
    Fetch a FRED series and return as a list of (date_str, value) tuples.

    Args:
        series_id: FRED series identifier (e.g., 'WRESBAL').
        observation_start: Start date in YYYY-MM-DD format. Default: 2020-01-01.
        observation_end: End date in YYYY-MM-DD format. Defaults to today.
        api_key: FRED API key. If None, reads from FRED_KEY env var.

    Returns:
        List of (date_str, float_value) tuples, sorted ascending by date.
        "." observations are filtered out.

    Raises:
        RuntimeError: if FRED_KEY is not set and no key provided.
        RuntimeError: if the HTTP request fails or the response is invalid.
        RuntimeError: if FRED returns no observations.
    """
    if api_key is None:
        api_key = os.environ.get("FRED_KEY")
    if not api_key:
        raise RuntimeError(
            "FRED_KEY environment variable is not set. "
            "Set FRED_KEY before calling fetch_fred_series()."
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
        raise RuntimeError(
            f"FRED fetch failed for series '{series_id}': {e}"
        ) from e

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
    records = []
    for obs in observations:
        if obs.get("value") != ".":
            try:
                records.append((obs["date"], float(obs["value"])))
            except (KeyError, ValueError):
                continue

    if not records:
        raise RuntimeError(
            f"FRED series '{series_id}' returned only missing values ('.')."
        )

    return records
