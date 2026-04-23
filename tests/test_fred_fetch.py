"""
Tests for src/macro/fetch/fred.py

Covers:
  - Valid FRED response is parsed into pd.Series with correct values
  - "." values (FRED missing data) are filtered out
  - HTTP error propagates as RuntimeError
  - Missing FRED_API_KEY raises RuntimeError
"""

import json
import os
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock

from src.macro.fetch.fred import fetch_fred_series


def _make_mock_response(observations: list, status_code: int = 200):
    """Create a mock requests.Response object."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = {"observations": observations}
    if status_code != 200:
        from requests.exceptions import HTTPError
        mock_resp.raise_for_status.side_effect = HTTPError(
            f"HTTP {status_code}", response=mock_resp
        )
    else:
        mock_resp.raise_for_status.return_value = None
    return mock_resp


class TestFredFetch:

    def test_valid_response_parsed(self):
        """Valid FRED response with numeric observations returns a pd.Series."""
        observations = [
            {"date": "2024-01-01", "value": "4.50"},
            {"date": "2024-02-01", "value": "4.55"},
            {"date": "2024-03-01", "value": "4.60"},
        ]
        mock_resp = _make_mock_response(observations)

        with patch("src.macro.fetch.fred.requests.get", return_value=mock_resp):
            series = fetch_fred_series("DGS10", api_key="test-key-123")

        assert isinstance(series, pd.Series)
        assert len(series) == 3
        assert series.iloc[0] == pytest.approx(4.50)
        assert series.iloc[1] == pytest.approx(4.55)
        assert series.iloc[2] == pytest.approx(4.60)

    def test_dot_values_filtered(self):
        """'.' values (FRED missing data placeholders) are filtered from the result."""
        observations = [
            {"date": "2024-01-01", "value": "4.50"},
            {"date": "2024-02-01", "value": "."},   # missing
            {"date": "2024-03-01", "value": "4.60"},
            {"date": "2024-04-01", "value": "."},   # missing
            {"date": "2024-05-01", "value": "4.65"},
        ]
        mock_resp = _make_mock_response(observations)

        with patch("src.macro.fetch.fred.requests.get", return_value=mock_resp):
            series = fetch_fred_series("DGS10", api_key="test-key-123")

        assert len(series) == 3
        assert "." not in series.values

    def test_http_error_raises_runtime_error(self):
        """HTTP error from FRED raises RuntimeError with series_id in message."""
        mock_resp = _make_mock_response([], status_code=403)

        with patch("src.macro.fetch.fred.requests.get", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="DGS10"):
                fetch_fred_series("DGS10", api_key="test-key-123")

    def test_missing_api_key_raises_runtime_error(self, monkeypatch):
        """RuntimeError raised when FRED_API_KEY not set and no key provided."""
        monkeypatch.delenv("FRED_API_KEY", raising=False)

        with pytest.raises(RuntimeError, match="FRED_API_KEY"):
            fetch_fred_series("DGS10")

    def test_api_key_from_env(self, monkeypatch):
        """API key is read from FRED_API_KEY env var when not explicitly provided."""
        monkeypatch.setenv("FRED_API_KEY", "env-key-456")
        observations = [{"date": "2024-01-01", "value": "4.0"}]
        mock_resp = _make_mock_response(observations)

        with patch("src.macro.fetch.fred.requests.get", return_value=mock_resp) as mock_get:
            series = fetch_fred_series("EFFR")  # no api_key= argument

        assert len(series) == 1
        # Verify api_key was passed in the request params
        call_kwargs = mock_get.call_args
        params = call_kwargs[1]["params"] if call_kwargs[1] else call_kwargs[0][1]
        assert params["api_key"] == "env-key-456"

    def test_series_has_datetimeindex(self):
        """Returned Series has a DatetimeIndex."""
        observations = [
            {"date": "2024-01-01", "value": "3.5"},
            {"date": "2024-02-01", "value": "3.6"},
        ]
        mock_resp = _make_mock_response(observations)

        with patch("src.macro.fetch.fred.requests.get", return_value=mock_resp):
            series = fetch_fred_series("CPIAUCSL", api_key="test-key")

        assert isinstance(series.index, pd.DatetimeIndex)

    def test_all_missing_raises_runtime_error(self):
        """RuntimeError raised if all observations are '.' (no valid data)."""
        observations = [
            {"date": "2024-01-01", "value": "."},
            {"date": "2024-02-01", "value": "."},
        ]
        mock_resp = _make_mock_response(observations)

        with patch("src.macro.fetch.fred.requests.get", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="missing values"):
                fetch_fred_series("DGS10", api_key="test-key")

    def test_empty_observations_raises_runtime_error(self):
        """RuntimeError raised if observations list is empty."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"observations": []}

        with patch("src.macro.fetch.fred.requests.get", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="no observations"):
                fetch_fred_series("EFFR", api_key="test-key")

    def test_network_error_raises_runtime_error(self):
        """Network-level exception is wrapped in RuntimeError."""
        import requests as req_lib
        with patch(
            "src.macro.fetch.fred.requests.get",
            side_effect=req_lib.exceptions.ConnectionError("network down"),
        ):
            with pytest.raises(RuntimeError, match="FRED fetch failed"):
                fetch_fred_series("DGS10", api_key="test-key")
