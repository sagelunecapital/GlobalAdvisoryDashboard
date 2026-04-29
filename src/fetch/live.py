import math

import pandas as pd

from src.fetch.spx import fetch_spx
from src.fetch.mmth import fetch_mmth
from src.db.append import append_day


class FetchError(RuntimeError):
    """Raised when one or more indicator fetches fail or return null/non-finite values."""

    def __init__(self, message: str, failed_indicators: list = None):
        super().__init__(message)
        self.failed_indicators = [x for x in (failed_indicators or []) if x is not None]


def fetch_live(db_path: str, _spx_df=None, _mmth_series=None) -> dict:
    """
    Fetch current indicator values, validate, and persist to DB.

    Args:
        db_path: Path to the SQLite indicators database.
        _spx_df: (testing only) inject SPX DataFrame; bypasses fetch_spx() call.
        _mmth_series: (testing only) inject MMTH Series; bypasses fetch_mmth() call.

    Returns:
        dict with keys: date (str), spx_daily_high (float), spx_12d_ema (float),
                        spx_25d_ema (float), mmth (float)

    Raises:
        FetchError: if any fetch fails (AC5) or any value is null/NaN (AC6).
        RuntimeError: if DB persistence fails (propagated from append_day).
    """
    errors = []
    spx_row = None
    mmth_value = None

    # SPX fetch
    try:
        spx_df = _spx_df if _spx_df is not None else fetch_spx(period="2y")
        if len(spx_df) == 0:
            raise RuntimeError("SPX DataFrame is empty")
        spx_row = spx_df.iloc[-1]
    except Exception as e:
        errors.append(f"SPX fetch failed: {e}")

    # MMTH fetch
    try:
        mmth_series = _mmth_series if _mmth_series is not None else fetch_mmth(period="2y")
        if len(mmth_series) == 0:
            raise RuntimeError("MMTH Series is empty")
        mmth_value = mmth_series.iloc[-1]
    except Exception as e:
        errors.append(f"MMTH fetch failed: {e}")

    # AC5: surface fetch errors
    if errors:
        failed = []
        if any("SPX" in e for e in errors):
            failed.append("SPX (daily high, 12d EMA, 25d EMA)")
        if any("MMTH" in e for e in errors):
            failed.append("MMTH")
        raise FetchError("; ".join(errors), failed_indicators=failed)

    # AC6: validate — check for None and NaN/non-finite values
    date_val = spx_row["date"]
    spx_high = spx_row["spx_daily_high"]
    spx_12 = spx_row["spx_12d_ema"]
    spx_25 = spx_row["spx_25d_ema"]
    mmth_v = mmth_value

    null_indicators = []
    for name, val in [
        ("spx_daily_high", spx_high),
        ("spx_12d_ema", spx_12),
        ("spx_25d_ema", spx_25),
        ("mmth", mmth_v),
    ]:
        if val is None or pd.isna(val):
            null_indicators.append(name)

    if null_indicators:
        raise FetchError(
            f"Fetch succeeded but values are null/missing: {null_indicators}. No data persisted.",
            failed_indicators=null_indicators,
        )

    spx_high_f = float(spx_high)
    spx_12_f = float(spx_12)
    spx_25_f = float(spx_25)
    mmth_f = float(mmth_v)

    for name, val in [
        ("spx_daily_high", spx_high_f),
        ("spx_12d_ema", spx_12_f),
        ("spx_25d_ema", spx_25_f),
        ("mmth", mmth_f),
    ]:
        if not math.isfinite(val):
            raise FetchError(
                f"Value for {name} is not finite ({val}). No data persisted.",
                failed_indicators=[name],
            )

    # AC7: persist
    append_day(
        db_path=db_path,
        date=str(date_val),
        spx_daily_high=spx_high_f,
        spx_12d_ema=spx_12_f,
        spx_25d_ema=spx_25_f,
        mmth=mmth_f,
    )

    return {
        "date": str(date_val),
        "spx_daily_high": spx_high_f,
        "spx_12d_ema": spx_12_f,
        "spx_25d_ema": spx_25_f,
        "mmth": mmth_f,
    }
