"""
Tests for src/macro/fetch/gdpnow.py

Covers:
  - Mock Excel parsed — most recent row extracted
  - HTTP error raises RuntimeError
  - Unexpected columns raise RuntimeError with column list
"""

import io
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock

from src.macro.fetch.gdpnow import fetch_gdpnow


def _make_excel_bytes(df: pd.DataFrame) -> bytes:
    """Serialize a DataFrame to Excel bytes using openpyxl engine."""
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    buf.seek(0)
    return buf.read()


def _make_mock_response(content: bytes, status_code: int = 200):
    """Create a mock requests.Response with binary content."""
    mock_resp = MagicMock()
    mock_resp.content = content
    mock_resp.status_code = status_code
    if status_code != 200:
        from requests.exceptions import HTTPError
        mock_resp.raise_for_status.side_effect = HTTPError(
            f"HTTP {status_code}", response=mock_resp
        )
    else:
        mock_resp.raise_for_status.return_value = None
    return mock_resp


class TestGDPNowFetch:

    def test_most_recent_row_extracted(self):
        """Most recent (last) GDPNow estimate is returned."""
        df = pd.DataFrame({
            "Date": ["2024-01-17", "2024-01-24", "2024-01-31"],
            "GDPNow": [2.3, 2.5, 2.7],
        })
        content = _make_excel_bytes(df)
        mock_resp = _make_mock_response(content)

        with patch("src.macro.fetch.gdpnow.requests.get", return_value=mock_resp):
            date_str, value = fetch_gdpnow()

        assert date_str == "2024-01-31"
        assert abs(value - 2.7) < 1e-6

    def test_multiple_rows_returns_latest(self):
        """When multiple rows exist, the most recent date is returned."""
        df = pd.DataFrame({
            "Date": ["2023-10-01", "2023-11-01", "2024-02-14"],
            "GDPNow": [1.5, 1.8, 3.2],
        })
        content = _make_excel_bytes(df)
        mock_resp = _make_mock_response(content)

        with patch("src.macro.fetch.gdpnow.requests.get", return_value=mock_resp):
            date_str, value = fetch_gdpnow()

        assert date_str == "2024-02-14"
        assert abs(value - 3.2) < 1e-6

    def test_http_error_raises_runtime_error(self):
        """HTTP error raises RuntimeError."""
        mock_resp = _make_mock_response(b"", status_code=503)

        with patch("src.macro.fetch.gdpnow.requests.get", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="HTTP"):
                fetch_gdpnow()

    def test_network_error_raises_runtime_error(self):
        """Network exception (ConnectionError) raises RuntimeError."""
        import requests as req_lib
        with patch(
            "src.macro.fetch.gdpnow.requests.get",
            side_effect=req_lib.exceptions.ConnectionError("unreachable"),
        ):
            with pytest.raises(RuntimeError, match="GDPNow"):
                fetch_gdpnow()

    def test_unexpected_columns_raises_runtime_error(self):
        """Unexpected column names raise RuntimeError with column list."""
        # No 'GDPNow' or 'Nowcast' column, and multiple numeric columns → ambiguous
        df = pd.DataFrame({
            "col_a": ["2024-01-01", "2024-02-01"],
            "alpha": [1.1, 1.2],
            "beta": [2.1, 2.2],
        })
        content = _make_excel_bytes(df)
        mock_resp = _make_mock_response(content)

        with patch("src.macro.fetch.gdpnow.requests.get", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="unexpected columns"):
                fetch_gdpnow()

    def test_nowcast_column_name_accepted(self):
        """Column named 'Nowcast' is correctly identified as the estimate column."""
        df = pd.DataFrame({
            "Date": ["2024-03-06", "2024-03-13"],
            "Nowcast": [2.8, 2.9],
        })
        content = _make_excel_bytes(df)
        mock_resp = _make_mock_response(content)

        with patch("src.macro.fetch.gdpnow.requests.get", return_value=mock_resp):
            date_str, value = fetch_gdpnow()

        assert date_str == "2024-03-13"
        assert abs(value - 2.9) < 1e-6

    def test_returns_tuple_date_float(self):
        """Return type is (str, float)."""
        df = pd.DataFrame({
            "Date": ["2024-04-01"],
            "GDPNow": [1.9],
        })
        content = _make_excel_bytes(df)
        mock_resp = _make_mock_response(content)

        with patch("src.macro.fetch.gdpnow.requests.get", return_value=mock_resp):
            result = fetch_gdpnow()

        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], str)
        assert isinstance(result[1], float)
