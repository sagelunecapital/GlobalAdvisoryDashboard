"""
Tests for Story E01S03: Market Regime Classification.

Coverage (one test per AC):
  AC1  -- SPX >= 12d EMA, divergence=none     -> Green, condition=1
  AC2  -- SPX >= 12d EMA, divergence=bearish  -> Yellow, condition=2
  AC3  -- SPX >= 12d EMA, divergence=bullish  -> Green, condition=3 (absorbed)
  AC4  -- SPX between EMAs, divergence=none   -> Yellow, condition=4
  AC5  -- SPX between EMAs, divergence=bullish-> Yellow, condition=5 (absorbed)
  AC6  -- SPX between EMAs, divergence=bearish-> Red, condition=6
  AC7  -- SPX < 25d EMA, divergence=bullish   -> Yellow, condition=7
  AC8  -- SPX < 25d EMA, divergence=none      -> Red, condition=8
  AC9  -- SPX < 25d EMA, divergence=bearish   -> Red, condition=9
  AC10 -- Any missing input -> unclassified (label=None, condition=None)
           Sub-cases: spx=None, ema_12=None, ema_25=None, divergence=None,
                      divergence=DATA_GAP

All tests use the pure classify_regime() function; no DB required.
"""

from __future__ import annotations

import pytest

from src.analysis.divergence import DivergenceResult
from src.analysis.regime import RegimeLabel, RegimeResult, classify_regime


# ---------------------------------------------------------------------------
# Shared price constants (above/between/below relative to 12d and 25d EMA)
# ---------------------------------------------------------------------------

EMA_12 = 5000.0
EMA_25 = 4900.0

SPX_ABOVE   = 5100.0   # >= EMA_12 (above zone)
SPX_BETWEEN = 4950.0   # < EMA_12 AND >= EMA_25 (between zone)
SPX_BELOW   = 4800.0   # < EMA_25 (below zone)

# Edge cases used for AC1 equality check (SPX exactly at EMA_12)
SPX_AT_12   = EMA_12


# ---------------------------------------------------------------------------
# AC1: above + no divergence -> Green, condition 1
# ---------------------------------------------------------------------------

class TestAC1AboveNoDivergence:

    def test_basic(self):
        result = classify_regime(SPX_ABOVE, EMA_12, EMA_25, DivergenceResult.NO_DIVERGENCE)
        assert result.label == RegimeLabel.GREEN
        assert result.condition == 1

    def test_spx_exactly_at_12d_ema_counts_as_above(self):
        """SPX == 12d EMA satisfies the >= condition -> above zone -> condition 1."""
        result = classify_regime(SPX_AT_12, EMA_12, EMA_25, DivergenceResult.NO_DIVERGENCE)
        assert result.label == RegimeLabel.GREEN
        assert result.condition == 1

    def test_explanation_not_empty(self):
        result = classify_regime(SPX_ABOVE, EMA_12, EMA_25, DivergenceResult.NO_DIVERGENCE)
        assert len(result.explanation) > 0


# ---------------------------------------------------------------------------
# AC2: above + bearish divergence -> Yellow, condition 2
# ---------------------------------------------------------------------------

class TestAC2AboveBearish:

    def test_basic(self):
        result = classify_regime(SPX_ABOVE, EMA_12, EMA_25, DivergenceResult.BEARISH)
        assert result.label == RegimeLabel.YELLOW
        assert result.condition == 2

    def test_explanation_references_bearish(self):
        result = classify_regime(SPX_ABOVE, EMA_12, EMA_25, DivergenceResult.BEARISH)
        assert "BEARISH" in result.explanation


# ---------------------------------------------------------------------------
# AC3: above + bullish divergence -> Green, condition 3 (absorbed)
# ---------------------------------------------------------------------------

class TestAC3AboveBullishAbsorbed:

    def test_basic(self):
        result = classify_regime(SPX_ABOVE, EMA_12, EMA_25, DivergenceResult.BULLISH)
        assert result.label == RegimeLabel.GREEN
        assert result.condition == 3

    def test_not_yellow(self):
        result = classify_regime(SPX_ABOVE, EMA_12, EMA_25, DivergenceResult.BULLISH)
        assert result.label != RegimeLabel.YELLOW


# ---------------------------------------------------------------------------
# AC4: between + no divergence -> Yellow, condition 4
# ---------------------------------------------------------------------------

class TestAC4BetweenNoDivergence:

    def test_basic(self):
        result = classify_regime(SPX_BETWEEN, EMA_12, EMA_25, DivergenceResult.NO_DIVERGENCE)
        assert result.label == RegimeLabel.YELLOW
        assert result.condition == 4

    def test_spx_exactly_at_25d_ema_counts_as_between(self):
        """SPX == 25d EMA satisfies >= 25d but < 12d -> between zone -> condition 4."""
        result = classify_regime(EMA_25, EMA_12, EMA_25, DivergenceResult.NO_DIVERGENCE)
        assert result.label == RegimeLabel.YELLOW
        assert result.condition == 4


# ---------------------------------------------------------------------------
# AC5: between + bullish divergence -> Yellow, condition 5 (absorbed)
# ---------------------------------------------------------------------------

class TestAC5BetweenBullishAbsorbed:

    def test_basic(self):
        result = classify_regime(SPX_BETWEEN, EMA_12, EMA_25, DivergenceResult.BULLISH)
        assert result.label == RegimeLabel.YELLOW
        assert result.condition == 5

    def test_not_green(self):
        result = classify_regime(SPX_BETWEEN, EMA_12, EMA_25, DivergenceResult.BULLISH)
        assert result.label != RegimeLabel.GREEN


# ---------------------------------------------------------------------------
# AC6: between + bearish divergence -> Red, condition 6
# ---------------------------------------------------------------------------

class TestAC6BetweenBearish:

    def test_basic(self):
        result = classify_regime(SPX_BETWEEN, EMA_12, EMA_25, DivergenceResult.BEARISH)
        assert result.label == RegimeLabel.RED
        assert result.condition == 6


# ---------------------------------------------------------------------------
# AC7: below + bullish divergence -> Yellow, condition 7
# ---------------------------------------------------------------------------

class TestAC7BelowBullish:

    def test_basic(self):
        result = classify_regime(SPX_BELOW, EMA_12, EMA_25, DivergenceResult.BULLISH)
        assert result.label == RegimeLabel.YELLOW
        assert result.condition == 7

    def test_not_red(self):
        result = classify_regime(SPX_BELOW, EMA_12, EMA_25, DivergenceResult.BULLISH)
        assert result.label != RegimeLabel.RED


# ---------------------------------------------------------------------------
# AC8: below + no divergence -> Red, condition 8
# ---------------------------------------------------------------------------

class TestAC8BelowNoDivergence:

    def test_basic(self):
        result = classify_regime(SPX_BELOW, EMA_12, EMA_25, DivergenceResult.NO_DIVERGENCE)
        assert result.label == RegimeLabel.RED
        assert result.condition == 8


# ---------------------------------------------------------------------------
# AC9: below + bearish divergence -> Red, condition 9
# ---------------------------------------------------------------------------

class TestAC9BelowBearish:

    def test_basic(self):
        result = classify_regime(SPX_BELOW, EMA_12, EMA_25, DivergenceResult.BEARISH)
        assert result.label == RegimeLabel.RED
        assert result.condition == 9

    def test_explanation_not_empty(self):
        result = classify_regime(SPX_BELOW, EMA_12, EMA_25, DivergenceResult.BEARISH)
        assert len(result.explanation) > 0


# ---------------------------------------------------------------------------
# AC10: any missing input -> unclassified (label=None, condition=None)
# ---------------------------------------------------------------------------

class TestAC10MissingInputUnclassified:

    def test_spx_price_none(self):
        result = classify_regime(None, EMA_12, EMA_25, DivergenceResult.NO_DIVERGENCE)
        assert result.label is None
        assert result.condition is None
        assert len(result.explanation) > 0

    def test_ema_12_none(self):
        result = classify_regime(SPX_ABOVE, None, EMA_25, DivergenceResult.NO_DIVERGENCE)
        assert result.label is None
        assert result.condition is None

    def test_ema_25_none(self):
        result = classify_regime(SPX_ABOVE, EMA_12, None, DivergenceResult.NO_DIVERGENCE)
        assert result.label is None
        assert result.condition is None

    def test_divergence_none(self):
        result = classify_regime(SPX_ABOVE, EMA_12, EMA_25, None)
        assert result.label is None
        assert result.condition is None

    def test_divergence_data_gap(self):
        result = classify_regime(SPX_ABOVE, EMA_12, EMA_25, DivergenceResult.DATA_GAP)
        assert result.label is None
        assert result.condition is None

    def test_all_none(self):
        result = classify_regime(None, None, None, None)
        assert result.label is None
        assert result.condition is None

    def test_explanation_present_on_missing_input(self):
        """Even unclassified results must carry a non-empty explanation."""
        result = classify_regime(None, EMA_12, EMA_25, DivergenceResult.NO_DIVERGENCE)
        assert isinstance(result.explanation, str)
        assert len(result.explanation) > 0


# ---------------------------------------------------------------------------
# EMA zone boundary: above takes precedence over between
# ---------------------------------------------------------------------------

class TestEmaZonePrecedence:

    def test_spx_equal_to_12d_ema_is_above_not_between(self):
        """
        When SPX == 12d EMA, the >= comparison assigns 'above' zone.
        No-divergence above -> condition 1 (Green), not condition 4 (Yellow).
        """
        result = classify_regime(EMA_12, EMA_12, EMA_25, DivergenceResult.NO_DIVERGENCE)
        assert result.condition == 1
        assert result.label == RegimeLabel.GREEN

    def test_spx_just_below_12d_ema_but_above_25d_is_between(self):
        spx = EMA_12 - 0.01
        result = classify_regime(spx, EMA_12, EMA_25, DivergenceResult.NO_DIVERGENCE)
        assert result.condition == 4
        assert result.label == RegimeLabel.YELLOW

    def test_spx_equal_to_25d_ema_is_between_not_below(self):
        result = classify_regime(EMA_25, EMA_12, EMA_25, DivergenceResult.NO_DIVERGENCE)
        assert result.condition == 4
        assert result.label == RegimeLabel.YELLOW

    def test_spx_just_below_25d_ema_is_below(self):
        spx = EMA_25 - 0.01
        result = classify_regime(spx, EMA_12, EMA_25, DivergenceResult.NO_DIVERGENCE)
        assert result.condition == 8
        assert result.label == RegimeLabel.RED


# ---------------------------------------------------------------------------
# RegimeResult immutability (frozen dataclass)
# ---------------------------------------------------------------------------

class TestRegimeResultImmutable:

    def test_frozen_dataclass_cannot_be_mutated(self):
        result = classify_regime(SPX_ABOVE, EMA_12, EMA_25, DivergenceResult.NO_DIVERGENCE)
        with pytest.raises((AttributeError, TypeError)):
            result.label = RegimeLabel.RED  # type: ignore[misc]
