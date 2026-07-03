#!/usr/bin/env python3
"""
FRED MCP Server — wraps existing project FRED fetch logic as MCP tools.

Tools:
  fetch_fred_series        — generic FRED series by ID, returns date/value records
  fetch_series_latest      — latest value + date for any FRED series
  fetch_gdpnow             — latest GDPNow real GDP estimate from Atlanta Fed
  fetch_monthly_indicators — all monthly macro indicators (CPI, PCE, PMI, NFP, etc.)

Requires: FRED_API_KEY environment variable.
"""

import json
import os
import sys

# Add project root so src.macro.fetch imports resolve
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server.fastmcp import FastMCP
from src.macro.fetch.fred import fetch_fred_series as _fetch_fred
from src.macro.fetch.gdpnow import fetch_gdpnow as _fetch_gdpnow
from src.macro.fetch.monthly_indicators import fetch_all_monthly

mcp = FastMCP("fred")


@mcp.tool()
def fetch_fred_series(
    series_id: str,
    observation_start: str = "2000-01-01",
    observation_end: str | None = None,
) -> str:
    """
    Fetch a FRED series and return all observations as JSON.

    Args:
        series_id: FRED series identifier (e.g. 'DGS10', 'A191RL1Q225SBEA').
        observation_start: Start date YYYY-MM-DD (default 2000-01-01).
        observation_end: End date YYYY-MM-DD (default: today).

    Returns:
        JSON: {"series_id": str, "records": [{"date": str, "value": float}, ...]}
    """
    series = _fetch_fred(series_id, observation_start, observation_end)
    records = [{"date": d.strftime("%Y-%m-%d"), "value": v} for d, v in series.items()]
    return json.dumps({"series_id": series_id, "records": records})


@mcp.tool()
def fetch_series_latest(
    series_id: str,
    observation_start: str = "2000-01-01",
) -> str:
    """
    Fetch the most recent value for a FRED series.

    Args:
        series_id: FRED series identifier.
        observation_start: Start date YYYY-MM-DD.

    Returns:
        JSON: {"series_id": str, "date": str, "value": float}
    """
    series = _fetch_fred(series_id, observation_start)
    return json.dumps({
        "series_id": series_id,
        "date": series.index[-1].strftime("%Y-%m-%d"),
        "value": round(float(series.iloc[-1]), 6),
    })


@mcp.tool()
def fetch_gdpnow() -> str:
    """
    Fetch the latest GDPNow real GDP estimate from the Atlanta Fed Excel endpoint.

    Returns:
        JSON: {"date": str, "gdpnow_estimate": float}
        estimate is the annualized real GDP growth rate (%).
    """
    date_str, estimate = _fetch_gdpnow()
    return json.dumps({"date": date_str, "gdpnow_estimate": estimate})


@mcp.tool()
def fetch_monthly_indicators(observation_start: str = "2000-01-01") -> str:
    """
    Fetch all monthly FRED macro indicators in one call.

    Indicators:
      CPI_YOY, CORE_CPI_YOY, PCE_YOY, CORE_PCE_YOY, PPI_YOY  (YoY %)
      RETAIL_SALES_MOM                                           (MoM %)
      BREAKEVEN_5Y, BREAKEVEN_2Y                                 (daily %)
      ISM_MFG_PMI, ISM_SVC_PMI                                  (index)
      UNRATE                                                     (%)
      NFP                                                        (thousands)

    Returns:
        JSON: {indicator_id: {latest_date, latest_value, series_length}, ...}
    """
    all_data = fetch_all_monthly(observation_start)
    result = {
        ind: {
            "latest_date": s.index[-1].strftime("%Y-%m-%d"),
            "latest_value": round(float(s.iloc[-1]), 4),
            "series_length": len(s),
        }
        for ind, s in all_data.items()
    }
    return json.dumps(result)


if __name__ == "__main__":
    mcp.run()
