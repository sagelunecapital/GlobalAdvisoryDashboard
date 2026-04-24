"""
SPX / MMTH Divergence Detection (Story E01S02)

Detects bearish or bullish divergence between SPX price action and the
MMTH breadth indicator (% stocks above 200-day moving average).

Governing Decisions:
  DEC-2026-04-18-01: SPX price = spx_daily_high column always.
  DEC-2026-04-18-02: Divergence anchor = the prior period's swing high/low.
                     All days in the same run compare against the SAME single
                     anchor. Yesterday's high within the same run is never the
                     anchor.
  DEC-2026-04-22-01: Python + SQLite + pandas only; no new runtime deps.

Swing Anchor Algorithm (DEC-2026-04-18-02):
  For BEARISH detection (prior swing HIGH anchor):
    1. In the 90-day window, find the global minimum (trough = the correction
       bottom that separated the prior high from the current run).
    2. All rows BEFORE the trough date form the "pre-trough" slice.
    3. The prior swing HIGH is the max of spx_daily_high in that pre-trough
       slice.  This is stable across all days in the same run because the
       trough date does not move while the market is above it.
    4. If the trough is the earliest point (no pre-trough rows), fall back to
       the overall window max as the anchor.

  For BULLISH detection (prior swing LOW anchor):
    1. Find the global maximum in the window (the peak of the rally that
       preceded the downturn).
    2. All rows on-or-after the peak form the "post-peak" slice.
    3. The prior swing LOW is the min of spx_daily_high in that post-peak
       slice.
    4. If no post-peak rows exist, fall back to the overall window min.
"""

from enum import Enum

import pandas as pd

from src.db.schema import get_connection


# ---------------------------------------------------------------------------
# Module-level constant
# ---------------------------------------------------------------------------

SWING_LOOKBACK_DAYS: int = 90
"""
Calendar days of history required to identify a valid swing anchor.
A window shorter than this is treated as insufficient (DATA_GAP).
The query fetches all rows with date < as_of_date; the earliest row must be
at least SWING_LOOKBACK_DAYS calendar days before as_of_date.
"""


# ---------------------------------------------------------------------------
# Result enum
# ---------------------------------------------------------------------------

class DivergenceResult(Enum):
    BEARISH = "BEARISH"
    BULLISH = "BULLISH"
    NO_DIVERGENCE = "NO_DIVERGENCE"
    DATA_GAP = "DATA_GAP"


# ---------------------------------------------------------------------------
# Main detection function
# ---------------------------------------------------------------------------

def detect_divergence(
    db_path: str,
    as_of_date: str,
    _db_rows=None,
) -> tuple[DivergenceResult, str]:
    """
    Detect SPX / MMTH divergence for a given evaluation date.

    Parameters
    ----------
    db_path : str
        Path to the SQLite indicator database (ignored when _db_rows provided).
    as_of_date : str
        ISO-8601 date being evaluated (YYYY-MM-DD).
    _db_rows : list[tuple[str, float, float]] | None
        Injectable test override.  Each tuple is (date_str, spx_daily_high, mmth)
        covering ALL rows including the as_of_date row.  When supplied, no DB
        query is made and db_path is not opened.

    Returns
    -------
    tuple[DivergenceResult, str]
        (result_enum, human_readable_explanation)

        Cases:
          BEARISH       — SPX new high + MMTH lower than anchor
          BULLISH       — SPX new low  + MMTH higher than anchor
          NO_DIVERGENCE — neither condition met
          DATA_GAP      — insufficient / missing data; explanation is
                          user-visible; downstream consumers must treat this
                          as "unavailable", NOT as clean no-divergence (AC5)
    """
    # ------------------------------------------------------------------
    # 1. Load rows (DB or injected)
    # ------------------------------------------------------------------
    if _db_rows is not None:
        all_rows = list(_db_rows)
    else:
        all_rows = _load_from_db(db_path, as_of_date)

    # Split into window (prior days) and current row
    window_rows = [(d, h, m) for d, h, m in all_rows if d < as_of_date]
    current_rows = [(d, h, m) for d, h, m in all_rows if d == as_of_date]

    # ------------------------------------------------------------------
    # 2. DATA_GAP checks
    # ------------------------------------------------------------------

    # AC5-a: No row for as_of_date
    if not current_rows:
        return (
            DivergenceResult.DATA_GAP,
            f"DATA_GAP: no indicator row found for evaluation date {as_of_date}. "
            "This date may not yet be loaded into the database.",
        )

    # AC5-b: Zero prior rows
    if not window_rows:
        return (
            DivergenceResult.DATA_GAP,
            f"DATA_GAP: no prior-date rows found before {as_of_date}. "
            f"At least {SWING_LOOKBACK_DAYS} calendar days of history are required.",
        )

    # Build DataFrame from window rows for vectorised operations
    window_df = pd.DataFrame(window_rows, columns=["date", "spx_daily_high", "mmth"])
    window_df = window_df.sort_values("date").reset_index(drop=True)

    # AC5-c: Insufficient history (< SWING_LOOKBACK_DAYS calendar days)
    earliest_days_before = (
        pd.Timestamp(as_of_date) - pd.Timestamp(window_df.iloc[0]["date"])
    ).days
    if earliest_days_before < SWING_LOOKBACK_DAYS:
        return (
            DivergenceResult.DATA_GAP,
            f"DATA_GAP: earliest prior row is only {earliest_days_before} calendar days "
            f"before {as_of_date}; {SWING_LOOKBACK_DAYS} days are required to identify a "
            "reliable swing anchor. Load more historical data to resolve this gap.",
        )

    # Extract current values
    current_spx_high = current_rows[0][1]
    current_mmth = current_rows[0][2]

    # ------------------------------------------------------------------
    # 3. Swing anchor — BEARISH (prior swing HIGH)
    # ------------------------------------------------------------------
    trough_idx = window_df["spx_daily_high"].idxmin()
    trough_date = window_df.loc[trough_idx, "date"]

    pre_trough_df = window_df[window_df["date"] < trough_date]
    if pre_trough_df.empty:
        # Trough is the earliest point — fall back to window max
        prior_high_idx = window_df["spx_daily_high"].idxmax()
    else:
        prior_high_idx = pre_trough_df["spx_daily_high"].idxmax()

    prior_high_date = window_df.loc[prior_high_idx, "date"]
    prior_high_spx = window_df.loc[prior_high_idx, "spx_daily_high"]
    prior_high_mmth = window_df.loc[prior_high_idx, "mmth"]

    # AC5-d: MMTH missing at anchor
    if pd.isna(prior_high_mmth):
        return (
            DivergenceResult.DATA_GAP,
            f"DATA_GAP: MMTH is missing (NaN) for the bearish anchor date {prior_high_date}. "
            "Divergence cannot be computed without MMTH at the anchor.",
        )

    # ------------------------------------------------------------------
    # 4. Swing anchor — BULLISH (prior swing LOW)
    # ------------------------------------------------------------------
    peak_idx = window_df["spx_daily_high"].idxmax()
    peak_date = window_df.loc[peak_idx, "date"]

    post_peak_df = window_df[window_df["date"] >= peak_date]
    if post_peak_df.empty:
        prior_low_idx = window_df["spx_daily_high"].idxmin()
    else:
        prior_low_idx = post_peak_df["spx_daily_high"].idxmin()

    prior_low_date = window_df.loc[prior_low_idx, "date"]
    prior_low_spx = window_df.loc[prior_low_idx, "spx_daily_high"]
    prior_low_mmth = window_df.loc[prior_low_idx, "mmth"]

    # AC5-d: MMTH missing at bullish anchor
    if pd.isna(prior_low_mmth):
        return (
            DivergenceResult.DATA_GAP,
            f"DATA_GAP: MMTH is missing (NaN) for the bullish anchor date {prior_low_date}. "
            "Divergence cannot be computed without MMTH at the anchor.",
        )

    # ------------------------------------------------------------------
    # 5. Divergence classification (AC1, AC2, AC3)
    # ------------------------------------------------------------------

    # AC1 — Bearish: SPX new high, MMTH lower
    if current_spx_high > prior_high_spx and current_mmth < prior_high_mmth:
        return (
            DivergenceResult.BEARISH,
            f"Bearish divergence: SPX {current_spx_high:.2f} > prior high "
            f"{prior_high_spx:.2f} on {prior_high_date}; MMTH {current_mmth:.2f} < "
            f"{prior_high_mmth:.2f} at anchor",
        )

    # AC2 — Bullish: SPX new low, MMTH higher
    if current_spx_high < prior_low_spx and current_mmth > prior_low_mmth:
        return (
            DivergenceResult.BULLISH,
            f"Bullish divergence: SPX {current_spx_high:.2f} < prior low "
            f"{prior_low_spx:.2f} on {prior_low_date}; MMTH {current_mmth:.2f} > "
            f"{prior_low_mmth:.2f} at anchor",
        )

    # AC3 — No divergence
    return (
        DivergenceResult.NO_DIVERGENCE,
        f"No divergence detected as of {as_of_date}",
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _load_from_db(db_path: str, as_of_date: str) -> list[tuple]:
    """
    Load all indicator rows relevant to the divergence calculation.
    Returns a combined list of (date, spx_daily_high, mmth) tuples covering
    both prior rows (date < as_of_date) and the current date row (date = as_of_date).
    """
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT date, spx_daily_high, mmth
            FROM indicators
            WHERE date < :as_of_date
            ORDER BY date ASC
            """,
            {"as_of_date": as_of_date},
        )
        prior_rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT date, spx_daily_high, mmth
            FROM indicators
            WHERE date = :as_of_date
            """,
            {"as_of_date": as_of_date},
        )
        current_row = cursor.fetchone()
    finally:
        conn.close()

    rows = list(prior_rows)
    if current_row is not None:
        rows.append(current_row)
    return rows
