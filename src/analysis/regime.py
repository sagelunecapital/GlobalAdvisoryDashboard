"""
Market Regime Classification (Story E01S03)

Classifies the current market regime (Green / Yellow / Red) based on the
position of SPX relative to its 12-day and 25-day EMAs and the divergence
signal from SPX / MMTH breadth analysis.

Condition table:
  Zone     Divergence     Regime   Condition
  above    none           Green    1
  above    bearish        Yellow   2
  above    bullish        Green    3   (absorbed — bullish div while above 12d EMA)
  between  none           Yellow   4
  between  bullish        Yellow   5   (absorbed)
  between  bearish        Red      6
  below    bullish        Yellow   7
  below    none           Red      8
  below    bearish        Red      9

  Any missing input (None price/EMA or DATA_GAP divergence) -> unclassified
  (label=None, condition=None)

EMA zone rules (>= takes precedence):
  above   : SPX >= 12d EMA
  between : SPX <  12d EMA AND SPX >= 25d EMA
  below   : SPX <  25d EMA
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from src.analysis.divergence import DivergenceResult, detect_divergence
from src.db.schema import get_connection


# ---------------------------------------------------------------------------
# Enums and result type
# ---------------------------------------------------------------------------

class RegimeLabel(Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


@dataclass(frozen=True)
class RegimeResult:
    label: Optional[RegimeLabel]
    condition: Optional[int]
    explanation: str


# ---------------------------------------------------------------------------
# Pure classification function
# ---------------------------------------------------------------------------

def classify_regime(
    spx_price: Optional[float],
    ema_12: Optional[float],
    ema_25: Optional[float],
    divergence: Optional[DivergenceResult],
) -> RegimeResult:
    """
    Classify the market regime from the given inputs.

    Parameters
    ----------
    spx_price : float | None
        Current SPX price (spx_daily_close from the indicators table).
    ema_12 : float | None
        12-day EMA of SPX.
    ema_25 : float | None
        25-day EMA of SPX.
    divergence : DivergenceResult | None
        Divergence signal.  DATA_GAP or None both trigger unclassified output.

    Returns
    -------
    RegimeResult
        label=None, condition=None when any input is missing or DATA_GAP.
    """
    # AC10: missing inputs
    if spx_price is None or ema_12 is None or ema_25 is None:
        return RegimeResult(
            label=None,
            condition=None,
            explanation="Unclassified: one or more required inputs are missing (None).",
        )

    if divergence is None:
        return RegimeResult(
            label=None,
            condition=None,
            explanation="Unclassified: divergence signal is None.",
        )

    if divergence is DivergenceResult.DATA_GAP:
        return RegimeResult(
            label=None,
            condition=None,
            explanation="Unclassified: divergence signal is DATA_GAP — insufficient data.",
        )

    # Determine EMA zone (>= takes precedence)
    if spx_price >= ema_12:
        zone = "above"
    elif spx_price >= ema_25:
        zone = "between"
    else:
        zone = "below"

    # Map (zone, divergence) -> (condition, label)
    _TABLE: dict[tuple[str, DivergenceResult], tuple[int, RegimeLabel]] = {
        ("above",   DivergenceResult.NO_DIVERGENCE): (1, RegimeLabel.GREEN),
        ("above",   DivergenceResult.BEARISH):       (2, RegimeLabel.YELLOW),
        ("above",   DivergenceResult.BULLISH):       (3, RegimeLabel.GREEN),
        ("between", DivergenceResult.NO_DIVERGENCE): (4, RegimeLabel.YELLOW),
        ("between", DivergenceResult.BULLISH):       (5, RegimeLabel.YELLOW),
        ("between", DivergenceResult.BEARISH):       (6, RegimeLabel.RED),
        ("below",   DivergenceResult.BULLISH):       (7, RegimeLabel.YELLOW),
        ("below",   DivergenceResult.NO_DIVERGENCE): (8, RegimeLabel.RED),
        ("below",   DivergenceResult.BEARISH):       (9, RegimeLabel.RED),
    }

    condition, label = _TABLE[(zone, divergence)]

    explanation = (
        f"Regime={label.value}, condition={condition}: "
        f"SPX={spx_price:.2f} is {zone} EMAs "
        f"(12d={ema_12:.2f}, 25d={ema_25:.2f}), "
        f"divergence={divergence.value}"
    )

    return RegimeResult(label=label, condition=condition, explanation=explanation)


# ---------------------------------------------------------------------------
# DB-backed classification
# ---------------------------------------------------------------------------

def classify_regime_from_db(db_path: str, as_of_date: str) -> RegimeResult:
    """
    Load the indicator row for as_of_date from the SQLite database, run
    divergence detection, and return the classified regime.

    Parameters
    ----------
    db_path : str
        Path to the SQLite indicators database.
    as_of_date : str
        ISO-8601 date string (YYYY-MM-DD) to classify.

    Returns
    -------
    RegimeResult
        Unclassified if any required data is missing or divergence=DATA_GAP.
    """
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT spx_daily_close, spx_12d_ema, spx_25d_ema
            FROM indicators
            WHERE date = :date
            """,
            {"date": as_of_date},
        )
        row = cursor.fetchone()
    finally:
        conn.close()

    if row is None:
        return RegimeResult(
            label=None,
            condition=None,
            explanation=f"Unclassified: no indicator row found for {as_of_date}.",
        )

    spx_price, ema_12, ema_25 = row

    divergence, _div_explanation = detect_divergence(db_path, as_of_date)

    return classify_regime(spx_price, ema_12, ema_25, divergence)
