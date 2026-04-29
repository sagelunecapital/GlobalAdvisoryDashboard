import math
import sqlite3

import numpy as np
import pandas as pd
import pytest

from src.fetch.live import FetchError, fetch_live


class TestFetchLive:

    def test_T1_happy_path_returns_correct_keys_and_non_null_values(
        self, tmp_db, sample_spx_df, sample_mmth_series
    ):
        result = fetch_live(tmp_db, _spx_df=sample_spx_df, _mmth_series=sample_mmth_series)
        assert set(result.keys()) == {"date", "spx_daily_high", "spx_12d_ema", "spx_25d_ema", "mmth"}
        assert isinstance(result["date"], str)
        for key in ("spx_daily_high", "spx_12d_ema", "spx_25d_ema", "mmth"):
            assert result[key] is not None
            assert math.isfinite(result[key])

    def test_T2_happy_path_db_row_persisted_with_matching_values(
        self, tmp_db, sample_spx_df, sample_mmth_series
    ):
        result = fetch_live(tmp_db, _spx_df=sample_spx_df, _mmth_series=sample_mmth_series)
        conn = sqlite3.connect(tmp_db)
        row = conn.execute(
            "SELECT date, spx_daily_high, spx_12d_ema, spx_25d_ema, mmth "
            "FROM indicators WHERE date = ?",
            (result["date"],),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == result["date"]
        assert abs(row[1] - result["spx_daily_high"]) < 0.001
        assert abs(row[2] - result["spx_12d_ema"]) < 0.001
        assert abs(row[3] - result["spx_25d_ema"]) < 0.001
        assert abs(row[4] - result["mmth"]) < 0.001

    def test_T3_idempotency_second_call_does_not_duplicate_row(
        self, tmp_db, sample_spx_df, sample_mmth_series
    ):
        fetch_live(tmp_db, _spx_df=sample_spx_df, _mmth_series=sample_mmth_series)
        fetch_live(tmp_db, _spx_df=sample_spx_df, _mmth_series=sample_mmth_series)
        conn = sqlite3.connect(tmp_db)
        count = conn.execute("SELECT COUNT(*) FROM indicators").fetchone()[0]
        conn.close()
        assert count == 1

    def test_T4_spx_fetch_failure_raises_fetch_error_with_spx_in_message_db_untouched(
        self, tmp_db, sample_mmth_series, monkeypatch
    ):
        monkeypatch.setattr("src.fetch.live.fetch_spx", lambda **_: (_ for _ in ()).throw(RuntimeError("network error")))
        with pytest.raises(FetchError) as exc_info:
            fetch_live(tmp_db, _mmth_series=sample_mmth_series)
        assert "SPX" in str(exc_info.value)
        conn = sqlite3.connect(tmp_db)
        # DB may not even exist yet; handle gracefully
        try:
            count = conn.execute("SELECT COUNT(*) FROM indicators").fetchone()[0]
        except Exception:
            count = 0
        finally:
            conn.close()
        assert count == 0

    def test_T5_mmth_fetch_failure_raises_fetch_error_with_mmth_in_message_db_untouched(
        self, tmp_db, sample_spx_df, monkeypatch
    ):
        monkeypatch.setattr("src.fetch.live.fetch_mmth", lambda **_: (_ for _ in ()).throw(RuntimeError("api error")))
        with pytest.raises(FetchError) as exc_info:
            fetch_live(tmp_db, _spx_df=sample_spx_df)
        assert "MMTH" in str(exc_info.value)
        conn = sqlite3.connect(tmp_db)
        try:
            count = conn.execute("SELECT COUNT(*) FROM indicators").fetchone()[0]
        except Exception:
            count = 0
        finally:
            conn.close()
        assert count == 0

    def test_T6_both_fetch_failures_raise_single_fetch_error_with_both_in_message(
        self, tmp_db, monkeypatch
    ):
        monkeypatch.setattr("src.fetch.live.fetch_spx", lambda **_: (_ for _ in ()).throw(RuntimeError("spx down")))
        monkeypatch.setattr("src.fetch.live.fetch_mmth", lambda **_: (_ for _ in ()).throw(RuntimeError("mmth down")))
        with pytest.raises(FetchError) as exc_info:
            fetch_live(tmp_db)
        msg = str(exc_info.value)
        assert "SPX" in msg
        assert "MMTH" in msg

    def test_T7_null_spx_daily_high_raises_fetch_error_db_count_zero(
        self, tmp_db, sample_spx_df, sample_mmth_series
    ):
        spx_df = sample_spx_df.copy()
        spx_df.loc[spx_df.index[-1], "spx_daily_high"] = float("nan")
        with pytest.raises(FetchError):
            fetch_live(tmp_db, _spx_df=spx_df, _mmth_series=sample_mmth_series)
        conn = sqlite3.connect(tmp_db)
        try:
            count = conn.execute("SELECT COUNT(*) FROM indicators").fetchone()[0]
        except Exception:
            count = 0
        finally:
            conn.close()
        assert count == 0

    def test_T8_null_spx_12d_ema_raises_fetch_error_db_count_zero(
        self, tmp_db, sample_spx_df, sample_mmth_series
    ):
        spx_df = sample_spx_df.copy()
        spx_df.loc[spx_df.index[-1], "spx_12d_ema"] = float("nan")
        with pytest.raises(FetchError):
            fetch_live(tmp_db, _spx_df=spx_df, _mmth_series=sample_mmth_series)
        conn = sqlite3.connect(tmp_db)
        try:
            count = conn.execute("SELECT COUNT(*) FROM indicators").fetchone()[0]
        except Exception:
            count = 0
        finally:
            conn.close()
        assert count == 0

    def test_T9_null_spx_25d_ema_raises_fetch_error_db_count_zero(
        self, tmp_db, sample_spx_df, sample_mmth_series
    ):
        spx_df = sample_spx_df.copy()
        spx_df.loc[spx_df.index[-1], "spx_25d_ema"] = float("nan")
        with pytest.raises(FetchError):
            fetch_live(tmp_db, _spx_df=spx_df, _mmth_series=sample_mmth_series)
        conn = sqlite3.connect(tmp_db)
        try:
            count = conn.execute("SELECT COUNT(*) FROM indicators").fetchone()[0]
        except Exception:
            count = 0
        finally:
            conn.close()
        assert count == 0

    def test_T10_null_mmth_raises_fetch_error_db_count_zero(
        self, tmp_db, sample_spx_df, sample_mmth_series
    ):
        mmth_series = sample_mmth_series.copy()
        mmth_series.iloc[-1] = float("nan")
        with pytest.raises(FetchError):
            fetch_live(tmp_db, _spx_df=sample_spx_df, _mmth_series=mmth_series)
        conn = sqlite3.connect(tmp_db)
        try:
            count = conn.execute("SELECT COUNT(*) FROM indicators").fetchone()[0]
        except Exception:
            count = 0
        finally:
            conn.close()
        assert count == 0

    def test_T11_fetch_error_is_subclass_of_runtime_error(self):
        assert issubclass(FetchError, RuntimeError)
