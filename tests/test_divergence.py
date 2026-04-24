"""
Tests for Story E01S02: SPX / MMTH Divergence Detection.

Coverage:
  T1  — bearish divergence (injection)
  T2  — bullish divergence (injection)
  T3  — no divergence: SPX new high, MMTH also higher
  T4  — no divergence: SPX new low, MMTH also lower
  T5  — no divergence: SPX within prior range
  T6  — DATA_GAP: zero prior rows
  T7  — DATA_GAP: insufficient history (< 90 calendar days)
  T8  — DATA_GAP: current date row missing
  T9  — anchor persists across two consecutive days in the same run (DEC-2026-04-18-02)
  T10 — story example (Jan 28 anchor, Apr 15 evaluation) → BEARISH
  T11 — DB read path, bearish result (uses tmp_db fixture)
  T12 — DB read path, DATA_GAP when DB has insufficient history (uses tmp_db fixture)
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.analysis.divergence import DivergenceResult, detect_divergence
from src.db.schema import create_schema


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rows(
    as_of_date: str,
    prior_tuples: list[tuple[str, float, float]],
    current_spx: float,
    current_mmth: float,
) -> list[tuple[str, float, float]]:
    """
    Build the _db_rows list: prior rows + the as_of_date current row.
    prior_tuples: list of (date_str, spx_daily_high, mmth) with date < as_of_date.
    """
    rows = list(prior_tuples)
    rows.append((as_of_date, current_spx, current_mmth))
    return rows


def _build_linear_prior_rows(
    as_of_date: str,
    n_days: int,
    base_price: float = 5000.0,
    base_mmth: float = 50.0,
) -> list[tuple[str, float, float]]:
    """
    Generate n_days of prior rows (date < as_of_date) with gently rising prices.
    Dates are calendar days, not business days, to keep arithmetic simple.
    """
    end = date.fromisoformat(as_of_date)
    rows = []
    for i in range(n_days):
        d = end - timedelta(days=n_days - i)
        rows.append((d.isoformat(), base_price + i * 5, base_mmth + i * 0.1))
    return rows


def _insert_rows(db_path: str, rows: list[tuple]) -> None:
    """Insert (date, spx_daily_high, mmth) rows into tmp_db (fills EMA cols with dummy values)."""
    from src.db.schema import get_connection

    conn = get_connection(db_path)
    try:
        conn.executemany(
            "INSERT OR REPLACE INTO indicators "
            "(date, spx_daily_high, spx_12d_ema, spx_25d_ema, mmth) "
            "VALUES (?, ?, ?, ?, ?)",
            [(d, h, h * 0.998, h * 0.995, m) for d, h, m in rows],
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

class TestDetectDivergence:

    # -----------------------------------------------------------------------
    # T1: Basic bearish divergence (injection)
    # -----------------------------------------------------------------------
    def test_T1_bearish_divergence_spx_new_high_mmth_lower(self):
        """
        Window structure:
          Day -100 to day -46: rising prices peaking at 5000 (mmth=70) near day -91
          Day -45 (trough): price = 4000, mmth = 50  (the correction bottom)
          Days -44 to -1: recovering but staying below 5000
          Current (as_of_date): spx=5100 (new high vs 5000), mmth=55 (<70 at anchor)
        Expected: BEARISH
        """
        as_of = "2099-04-15"
        as_of_ts = date.fromisoformat(as_of)

        prior_rows: list[tuple[str, float, float]] = []

        # Build 100 days of prior history
        # Phase 1: days -100 to -46 (55 days): peak on day -91 = 5000 / mmth=70
        for i in range(55):
            d = as_of_ts - timedelta(days=100 - i)
            # Prices rise to 5000 at index 9 (day -91) then decline
            offset = i - 9  # 0 at the peak day
            spx = 5000.0 - abs(offset) * 20
            spx = max(spx, 4200.0)
            mmth = 70.0 - abs(offset) * 0.3
            prior_rows.append((d.isoformat(), spx, mmth))

        # Phase 2: trough at day -45
        trough_date = (as_of_ts - timedelta(days=45)).isoformat()
        prior_rows.append((trough_date, 4000.0, 50.0))

        # Phase 3: recovery days -44 to -1 (44 days), prices rise but stay below 5000
        for i in range(44):
            d = as_of_ts - timedelta(days=44 - i)
            spx = 4100.0 + i * 20  # reaches ~4960 at day -1, still below 5000
            mmth = 51.0 + i * 0.1
            prior_rows.append((d.isoformat(), spx, mmth))

        rows = _make_rows(as_of, prior_rows, current_spx=5100.0, current_mmth=55.0)
        result, msg = detect_divergence("dummy", as_of, _db_rows=rows)

        assert result == DivergenceResult.BEARISH, f"Expected BEARISH, got {result}: {msg}"
        assert "5100" in msg or "5100.00" in msg
        assert len(msg) > 0

    # -----------------------------------------------------------------------
    # T2: Basic bullish divergence (injection)
    # -----------------------------------------------------------------------
    def test_T2_bullish_divergence_spx_new_low_mmth_higher(self):
        """
        Window structure:
          Peak near mid-window: spx=5500, mmth=65
          Post-peak trough near window end: spx=4800, mmth=40
          Current: spx=4700 (below 4800), mmth=45 (above 40) → BULLISH
        """
        as_of = "2099-06-01"
        as_of_ts = date.fromisoformat(as_of)

        prior_rows: list[tuple[str, float, float]] = []

        # Phase 1: flat start, then rise to peak at day -50
        for i in range(40):
            d = as_of_ts - timedelta(days=95 - i)
            prior_rows.append((d.isoformat(), 5000.0 + i * 10, 55.0 + i * 0.1))

        # Peak: day -55 (spx=5500, mmth=65)
        peak_date = (as_of_ts - timedelta(days=55)).isoformat()
        prior_rows.append((peak_date, 5500.0, 65.0))

        # Phase 2: decline after peak
        for i in range(54):
            d = as_of_ts - timedelta(days=54 - i)
            spx = 5400.0 - i * 12  # falls to ~4752 at day -1
            mmth = 64.0 - i * 0.5
            prior_rows.append((d.isoformat(), spx, mmth))

        # Prior trough near window end: use the row at day -1 (~4752)
        # Set explicit trough day
        trough_day = (as_of_ts - timedelta(days=2)).isoformat()
        prior_rows.append((trough_day, 4800.0, 40.0))

        rows = _make_rows(as_of, prior_rows, current_spx=4700.0, current_mmth=45.0)
        result, msg = detect_divergence("dummy", as_of, _db_rows=rows)

        assert result == DivergenceResult.BULLISH, f"Expected BULLISH, got {result}: {msg}"
        assert len(msg) > 0

    # -----------------------------------------------------------------------
    # T3: No divergence — SPX new high but MMTH also higher
    # -----------------------------------------------------------------------
    def test_T3_no_divergence_spx_new_high_mmth_also_higher(self):
        as_of = "2099-05-01"
        as_of_ts = date.fromisoformat(as_of)

        prior_rows: list[tuple[str, float, float]] = []
        # Build 95 days: trough at day -47, peak before trough at 5000/mmth=50
        for i in range(47):
            d = as_of_ts - timedelta(days=95 - i)
            prior_rows.append((d.isoformat(), 5000.0 - i * 10, 50.0 - i * 0.1))

        # Trough at day -48
        trough_date = (as_of_ts - timedelta(days=48)).isoformat()
        prior_rows.append((trough_date, 4500.0, 43.0))

        for i in range(47):
            d = as_of_ts - timedelta(days=47 - i)
            prior_rows.append((d.isoformat(), 4600.0 + i * 10, 44.0 + i * 0.1))

        # current: spx > prior high (5000) but mmth also > prior high mmth (50)
        rows = _make_rows(as_of, prior_rows, current_spx=5100.0, current_mmth=60.0)
        result, msg = detect_divergence("dummy", as_of, _db_rows=rows)

        assert result == DivergenceResult.NO_DIVERGENCE, f"Got {result}: {msg}"

    # -----------------------------------------------------------------------
    # T4: No divergence — SPX new low but MMTH also lower
    # -----------------------------------------------------------------------
    def test_T4_no_divergence_spx_new_low_mmth_also_lower(self):
        as_of = "2099-05-01"
        as_of_ts = date.fromisoformat(as_of)

        prior_rows: list[tuple[str, float, float]] = []

        # Peak at day -50
        peak_date = (as_of_ts - timedelta(days=50)).isoformat()
        prior_rows.append((peak_date, 5500.0, 70.0))

        # Fill before peak (older rows)
        for i in range(45):
            d = as_of_ts - timedelta(days=95 - i)
            prior_rows.append((d.isoformat(), 5000.0 + i * 10, 55.0 + i * 0.2))

        # Post-peak decline; trough near window end
        trough_date = (as_of_ts - timedelta(days=5)).isoformat()
        prior_rows.append((trough_date, 4900.0, 45.0))

        for i in range(44):
            d = as_of_ts - timedelta(days=49 - i)
            prior_rows.append((d.isoformat(), 5490.0 - i * 13, 69.5 - i * 0.5))

        # current: spx < prior low (4900) AND mmth < trough mmth (45) → no bullish div
        rows = _make_rows(as_of, prior_rows, current_spx=4800.0, current_mmth=40.0)
        result, msg = detect_divergence("dummy", as_of, _db_rows=rows)

        assert result == DivergenceResult.NO_DIVERGENCE, f"Got {result}: {msg}"

    # -----------------------------------------------------------------------
    # T5: No divergence — SPX within prior range
    # -----------------------------------------------------------------------
    def test_T5_no_divergence_spx_within_prior_range(self):
        as_of = "2099-05-01"
        prior_rows = _build_linear_prior_rows(as_of, n_days=100, base_price=4800.0, base_mmth=45.0)
        # current: spx in the middle of prior range, no new high/low
        rows = _make_rows(as_of, prior_rows, current_spx=5050.0, current_mmth=50.0)
        result, msg = detect_divergence("dummy", as_of, _db_rows=rows)
        assert result == DivergenceResult.NO_DIVERGENCE, f"Got {result}: {msg}"

    # -----------------------------------------------------------------------
    # T6: DATA_GAP — zero prior rows
    # -----------------------------------------------------------------------
    def test_T6_data_gap_zero_rows(self):
        result, msg = detect_divergence(
            "dummy",
            "2099-04-01",
            _db_rows=[("2099-04-01", 5000.0, 60.0)],
        )
        assert result == DivergenceResult.DATA_GAP
        assert len(msg) > 0

    # -----------------------------------------------------------------------
    # T7: DATA_GAP — insufficient history (< 90 calendar days)
    # -----------------------------------------------------------------------
    def test_T7_data_gap_insufficient_history_less_than_90_days(self):
        as_of = "2099-04-01"
        prior_rows = _build_linear_prior_rows(as_of, n_days=50, base_price=4900.0)
        rows = _make_rows(as_of, prior_rows, current_spx=5100.0, current_mmth=55.0)
        result, msg = detect_divergence("dummy", as_of, _db_rows=rows)
        assert result == DivergenceResult.DATA_GAP
        assert len(msg) > 0

    # -----------------------------------------------------------------------
    # T8: DATA_GAP — current date row missing
    # -----------------------------------------------------------------------
    def test_T8_data_gap_no_current_date_row(self):
        as_of = "2099-04-01"
        prior_rows = _build_linear_prior_rows(as_of, n_days=100, base_price=4800.0)
        # Do NOT add the as_of_date row
        result, msg = detect_divergence("dummy", as_of, _db_rows=prior_rows)
        assert result == DivergenceResult.DATA_GAP
        assert len(msg) > 0

    # -----------------------------------------------------------------------
    # T9: Anchor persists — same prior high used for two consecutive days (DEC-2026-04-18-02)
    # -----------------------------------------------------------------------
    def test_T9_anchor_persists_same_prior_high_for_two_days_in_same_run(self):
        """
        Verify that on Day 2 of a bearish-divergence run, the anchor is still
        the pre-trough peak from before the run began — not yesterday's new high.

        Setup:
          - 100 prior rows (relative to Apr 16 as anchor computation base)
          - Pre-trough peak: "2099-01-05", spx=7002.0, mmth=61.5
          - Trough (global min):  "2099-02-28", spx=6500.0, mmth=45.0
          - Post-trough recovery rows all below 7002

        Day 1 evaluation (Apr 15):
          current: spx=7026, mmth=55 → BEARISH (anchor=7002@2099-01-05)

        Day 2 evaluation (Apr 16):
          Apr 15 row is now a prior row (spx=7026, mmth=55)
          current: spx=7030, mmth=54
          The trough is still "2099-02-28" (6500, the global min in the window)
          pre-trough peak is still 7002 (on 2099-01-05)
          → BEARISH with same anchor 7002
        """
        # Fixed anchor and trough dates
        peak_date = "2099-01-05"
        trough_date = "2099-02-28"
        day1_date = "2099-04-15"
        day2_date = "2099-04-16"

        # Build shared prior rows (these are prior to day1)
        prior_base: list[tuple[str, float, float]] = []

        # Old rows before peak (2099-01-01 to 2099-01-04)
        for i in range(4):
            d = date(2099, 1, 1) + timedelta(days=i)
            prior_base.append((d.isoformat(), 6800.0 + i * 50, 58.0 + i * 0.5))

        # The peak itself
        prior_base.append((peak_date, 7002.0, 61.5))

        # Between peak and trough (2099-01-06 to 2099-02-27): declining
        d_iter = date(2099, 1, 6)
        end_before_trough = date(2099, 2, 27)
        step = 0
        while d_iter <= end_before_trough:
            prior_base.append((d_iter.isoformat(), 6990.0 - step * 10, 61.0 - step * 0.2))
            d_iter += timedelta(days=1)
            step += 1

        # The trough
        prior_base.append((trough_date, 6500.0, 45.0))

        # Post-trough recovery (2099-03-01 to 2099-04-14): recovering but below 7002
        d_iter = date(2099, 3, 1)
        end_recovery = date(2099, 4, 14)
        step = 0
        while d_iter <= end_recovery:
            prior_base.append((d_iter.isoformat(), 6510.0 + step * 12, 45.5 + step * 0.1))
            d_iter += timedelta(days=1)
            step += 1

        # --- Day 1 evaluation ---
        rows_day1 = list(prior_base) + [(day1_date, 7026.0, 55.0)]
        result1, msg1 = detect_divergence("dummy", day1_date, _db_rows=rows_day1)

        assert result1 == DivergenceResult.BEARISH, (
            f"Day 1 expected BEARISH, got {result1}: {msg1}"
        )
        assert "7002" in msg1, f"Day 1 anchor should be 7002, msg: {msg1}"

        # --- Day 2 evaluation --- (Apr 15 row is now a prior row)
        rows_day2 = list(prior_base) + [
            (day1_date, 7026.0, 55.0),   # now a prior row
            (day2_date, 7030.0, 54.0),   # current
        ]
        result2, msg2 = detect_divergence("dummy", day2_date, _db_rows=rows_day2)

        assert result2 == DivergenceResult.BEARISH, (
            f"Day 2 expected BEARISH, got {result2}: {msg2}"
        )
        assert "7002" in msg2, (
            f"Day 2 must use same anchor 7002 (not yesterday's 7026), msg: {msg2}"
        )

    # -----------------------------------------------------------------------
    # T10: Story example — Jan 28 anchor, Apr 15 evaluation → BEARISH
    # -----------------------------------------------------------------------
    def test_T10_story_example_apr15_jan28_bearish(self):
        """
        Mirror the canonical story example using 2099 dates for isolation.
          Prior high: 2099-01-28, spx=7002.0, mmth=61.50
          Trough:     2099-02-15, spx=6500.0, mmth=45.0
          Current:    2099-04-15, spx=7026.0, mmth=54.99
        Expected: BEARISH (current SPX > 7002, current MMTH < 61.50)
        """
        as_of = "2099-04-15"
        as_of_ts = date.fromisoformat(as_of)

        prior_rows: list[tuple[str, float, float]] = []

        # Old rows from 2099-01-05 to 2099-01-27 (rising to peak)
        d_iter = date(2099, 1, 5)
        while d_iter < date(2099, 1, 28):
            prior_rows.append((d_iter.isoformat(), 6900.0, 60.0))
            d_iter += timedelta(days=1)

        # Anchor (prior swing high)
        prior_rows.append(("2099-01-28", 7002.0, 61.50))

        # Between anchor and trough
        d_iter = date(2099, 1, 29)
        while d_iter < date(2099, 2, 15):
            prior_rows.append((d_iter.isoformat(), 6800.0, 54.0))
            d_iter += timedelta(days=1)

        # Trough
        prior_rows.append(("2099-02-15", 6500.0, 45.0))

        # Recovery rows (2099-02-16 to 2099-04-14)
        d_iter = date(2099, 2, 16)
        step = 0
        while d_iter < as_of_ts:
            prior_rows.append((d_iter.isoformat(), 6510.0 + step * 10, 46.0 + step * 0.05))
            d_iter += timedelta(days=1)
            step += 1

        rows = _make_rows(as_of, prior_rows, current_spx=7026.0, current_mmth=54.99)
        result, msg = detect_divergence("dummy", as_of, _db_rows=rows)

        assert result == DivergenceResult.BEARISH, f"Expected BEARISH, got {result}: {msg}"
        assert "7002" in msg
        assert "61.5" in msg or "61.50" in msg

    # -----------------------------------------------------------------------
    # T11: DB read path — bearish result (uses tmp_db fixture)
    # -----------------------------------------------------------------------
    def test_T11_reads_from_db_correctly_returns_bearish(self, tmp_db):
        create_schema(tmp_db)
        as_of = "2099-04-15"
        as_of_ts = date.fromisoformat(as_of)

        db_rows: list[tuple[str, float, float]] = []

        # Build same pattern as T10: 100 prior rows + current
        # Old flat rows
        for i in range(10):
            d = as_of_ts - timedelta(days=100 - i)
            db_rows.append((d.isoformat(), 6850.0 + i * 5, 59.0))

        # Peak row (pre-trough)
        peak_date = (as_of_ts - timedelta(days=90)).isoformat()
        db_rows.append((peak_date, 7002.0, 61.5))

        # Between peak and trough
        for i in range(40):
            d = as_of_ts - timedelta(days=89 - i)
            db_rows.append((d.isoformat(), 6900.0 - i * 10, 60.0 - i * 0.2))

        # Trough
        trough_d = (as_of_ts - timedelta(days=45)).isoformat()
        db_rows.append((trough_d, 6500.0, 45.0))

        # Recovery rows
        for i in range(44):
            d = as_of_ts - timedelta(days=44 - i)
            db_rows.append((d.isoformat(), 6510.0 + i * 12, 45.5 + i * 0.1))

        # Current row
        db_rows.append((as_of, 7026.0, 54.0))

        _insert_rows(tmp_db, db_rows)

        result, msg = detect_divergence(tmp_db, as_of)
        assert result == DivergenceResult.BEARISH, f"Got {result}: {msg}"
        assert len(msg) > 0

    # -----------------------------------------------------------------------
    # T12: DB read path — DATA_GAP when DB has < 90 days (uses tmp_db fixture)
    # -----------------------------------------------------------------------
    def test_T12_data_gap_returned_when_db_insufficient(self, tmp_db):
        create_schema(tmp_db)
        as_of = "2099-04-01"
        as_of_ts = date.fromisoformat(as_of)

        db_rows: list[tuple[str, float, float]] = []
        # Only 50 days of prior rows
        for i in range(50):
            d = as_of_ts - timedelta(days=50 - i)
            db_rows.append((d.isoformat(), 5000.0 + i * 5, 50.0))

        # Current row
        db_rows.append((as_of, 5300.0, 55.0))

        _insert_rows(tmp_db, db_rows)

        result, msg = detect_divergence(tmp_db, as_of)
        assert result == DivergenceResult.DATA_GAP
        assert len(msg) > 0
