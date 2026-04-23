"""
Atlanta Fed GDPNow fetch.

Fetches the most recent GDPNow real GDP estimate from the Atlanta Fed Excel endpoint.

Endpoint:
  https://www.atlantafed.org/-/media/documents/cqer/researchcq/gdpnow/GDPNow-model-output.xlsx

AC3: stored as current quarter's real-time estimate.
AC7: if GDPNow unavailable, visible error for that indicator only — other indicators not blocked.
"""

import io
import requests
import pandas as pd


GDPNOW_URL = (
    "https://www.atlantafed.org/-/media/documents/cqer/researchcq/"
    "gdpnow/GDPNow-model-output.xlsx"
)

_USER_AGENT = "Mozilla/5.0 (compatible; dashboard-fetch)"


def fetch_gdpnow() -> tuple:
    """
    Fetch the most recent GDPNow estimate from the Atlanta Fed.

    Returns:
        (date_str, estimate_value) — most recent estimate.
        - date_str: ISO-8601 YYYY-MM-DD of the estimate date.
        - estimate_value: float GDPNow real GDP growth estimate (annualized %).

    Raises:
        RuntimeError: on any failure (HTTP error, parse error, unexpected columns).
                      Caller must isolate this error — other indicators are not blocked.
    """
    try:
        response = requests.get(
            GDPNOW_URL,
            headers={"User-Agent": _USER_AGENT},
            timeout=60,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        raise RuntimeError(f"GDPNow: HTTP request failed: {e}") from e

    try:
        df = pd.read_excel(io.BytesIO(response.content), sheet_name=0, header=0)
    except Exception as e:
        raise RuntimeError(f"GDPNow: failed to parse Excel: {e}") from e

    if df.empty:
        raise RuntimeError("GDPNow: Excel sheet is empty")

    # Identify the date column (first column is typically the date)
    date_col = df.columns[0]

    # Identify the GDPNow estimate column — look for column containing 'GDPNow'
    # or 'Nowcast' (case-insensitive)
    gdpnow_col = None
    for col in df.columns[1:]:
        col_lower = str(col).lower()
        if "gdpnow" in col_lower or "nowcast" in col_lower:
            gdpnow_col = col
            break

    # If not found by name keyword, try the second column as fallback
    # but only if there are exactly 2 meaningful columns
    if gdpnow_col is None:
        # Check if there's a column that looks like a numeric estimate
        # column names from Atlanta Fed are sometimes date-formatted or numeric
        numeric_cols = [
            col for col in df.columns[1:]
            if pd.api.types.is_numeric_dtype(df[col])
            or df[col].dropna().apply(lambda x: isinstance(x, (int, float))).any()
        ]
        if len(numeric_cols) == 1:
            gdpnow_col = numeric_cols[0]
        else:
            raise RuntimeError(
                f"GDPNow: unexpected columns: {list(df.columns)}"
            )

    # Drop rows where either date or estimate is null
    df_clean = df[[date_col, gdpnow_col]].copy()
    df_clean.columns = ["date", "value"]
    df_clean = df_clean.dropna(subset=["date", "value"])

    if df_clean.empty:
        raise RuntimeError("GDPNow: no valid rows found after dropping nulls")

    # Parse dates — coerce errors to NaT
    df_clean["date"] = pd.to_datetime(df_clean["date"], errors="coerce")
    df_clean = df_clean.dropna(subset=["date"])

    if df_clean.empty:
        raise RuntimeError("GDPNow: no rows with valid dates found")

    # Ensure value is numeric
    df_clean["value"] = pd.to_numeric(df_clean["value"], errors="coerce")
    df_clean = df_clean.dropna(subset=["value"])

    if df_clean.empty:
        raise RuntimeError("GDPNow: no rows with valid numeric values found")

    # Take the most recent estimate
    latest = df_clean.sort_values("date").iloc[-1]
    date_str = latest["date"].strftime("%Y-%m-%d")
    estimate = float(latest["value"])

    return (date_str, estimate)
