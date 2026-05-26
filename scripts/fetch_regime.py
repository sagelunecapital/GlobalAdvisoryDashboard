#!/usr/bin/env python3
"""
Fetch S&P 500 Market Regime data and write prototypes/regime.json.

Sources:
  - SPX price + EMA(12,25): yfinance (^GSPC daily closes)
  - MMTH (% NYSE stocks above 200d MA): Barchart
  - NCFD close/high/low: Barchart
  - HIGQ, LOWQ (new 52-wk highs/lows counts): Barchart

Derived:
  - 12d EMA  = EWM(span=12)
  - 25d EMA  = EWM(span=25)
  - NHNL = HIGQ - LOWQ

Regime:
  - GREEN  : SPX >= EMA12 and MMTH >= 60
  - YELLOW : SPX >= EMA12 and MMTH <  60  (bearish breadth divergence)
           OR SPX <  EMA12 and MMTH >= 60  (bullish breadth divergence)
  - RED    : SPX <  EMA12 and MMTH <  60

NCFD label (priority: Hot > Cold > Warm > Lukewarm):
  - Hot      : NCFD session high >= 75
  - Cold     : NCFD session low  <= 25
  - Warm     : NCFD close > 50
  - Lukewarm : NCFD close > 25

NHNL label (priority: Hot > Highs > Cold > Lows > Neutral):
  - Hot    : NHNL >= 150 OR delta vs yesterday >= 100
  - Highs  : HIGQ >= 100
  - Cold   : NHNL < 0 for 3 consecutive days
  - Lows   : LOWQ >= 50
"""

import json
import os
import re
from datetime import datetime, timezone

import requests
import yfinance as yf

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
OUTPUT_PATH = os.path.join(SCRIPT_DIR, "..", "prototypes", "regime.json")

BC_URL_MMTH = "https://www.barchart.com/stocks/quotes/$MMTH/overview"
BC_URL_NCFD = "https://www.barchart.com/stocks/quotes/$NCFD/overview"
BC_URL_HIGQ = "https://www.barchart.com/stocks/quotes/$HIGQ/overview"
BC_URL_LOWQ = "https://www.barchart.com/stocks/quotes/$LOWQ/overview"
BC_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         "https://www.barchart.com/",
}


def _bc_extract(text, *field_names):
    """Extract a numeric field from Barchart HTML, trying multiple key names."""
    for fname in field_names:
        # Quoted number: "fieldName": "123.45"
        m = re.search(rf'"{re.escape(fname)}"\s*:\s*"([0-9]+(?:\.[0-9]+)?)"', text)
        if m:
            return float(m.group(1))
        # Unquoted number: "fieldName": 123.45
        m = re.search(rf'"{re.escape(fname)}"\s*:\s*([0-9]+(?:\.[0-9]+)?)(?=[,\s\}}])', text)
        if m:
            return float(m.group(1))
    return None


def fetch_spx():
    ticker = yf.Ticker("^GSPC")
    hist   = ticker.history(period="90d")
    if hist.empty:
        raise ValueError("No SPX history returned by yfinance")
    close = hist["Close"]
    spx   = float(close.iloc[-1])
    ema12 = float(close.ewm(span=12, adjust=False).mean().iloc[-1])
    ema25 = float(close.ewm(span=25, adjust=False).mean().iloc[-1])
    print(f"  SPX: {spx:.2f}", flush=True)
    print(f"  12d EMA: {ema12:.2f}  25d EMA: {ema25:.2f}", flush=True)
    return spx, round(ema12, 2), round(ema25, 2)


def fetch_mmth():
    r = requests.get(BC_URL_MMTH, headers=BC_HEADERS, timeout=30)
    r.raise_for_status()
    val = _bc_extract(r.text, 'lastPrice')
    if val is None:
        raise ValueError("Could not find lastPrice for $MMTH in Barchart HTML")
    print(f"  MMTH: {val:.2f}", flush=True)
    return round(val, 2)


def fetch_ncfd():
    """Return (close, high, low) for $NCFD from Barchart."""
    r = requests.get(BC_URL_NCFD, headers=BC_HEADERS, timeout=30)
    r.raise_for_status()
    text  = r.text
    close = _bc_extract(text, 'lastPrice')
    if close is None:
        raise ValueError("Could not find lastPrice for $NCFD in Barchart HTML")
    high  = _bc_extract(text, 'highPrice', 'dailyHighPrice') or close
    low   = _bc_extract(text, 'lowPrice',  'dailyLowPrice')  or close
    print(f"  NCFD: close={close:.2f}  high={high:.2f}  low={low:.2f}", flush=True)
    return round(close, 2), round(high, 2), round(low, 2)


def fetch_barchart_last(url, symbol):
    """Fetch the lastPrice for any Barchart symbol."""
    r = requests.get(url, headers=BC_HEADERS, timeout=30)
    r.raise_for_status()
    val = _bc_extract(r.text, 'lastPrice')
    if val is None:
        raise ValueError(f"Could not find lastPrice for {symbol} in Barchart HTML")
    print(f"  {symbol}: {val:.0f}", flush=True)
    return round(val, 2)


def classify(spx, ema12, mmth):
    if spx >= ema12 and mmth >= 60:
        return (
            "green", "none",
            f"SPX above 12d EMA and MMTH at {mmth:.1f}% — breadth confirming uptrend.",
        )
    elif spx >= ema12:
        return (
            "yellow", "bearish",
            f"SPX above 12d EMA but MMTH at {mmth:.1f}% — bearish breadth divergence active.",
        )
    elif mmth >= 60:
        return (
            "yellow", "bullish",
            f"SPX below 12d EMA but MMTH at {mmth:.1f}% — potential recovery forming.",
        )
    else:
        return (
            "red", "bearish",
            f"SPX below 12d EMA and MMTH at {mmth:.1f}% — confirmed bear market conditions.",
        )


def classify_ncfd(close, high, low):
    """Map NCFD session OHLC to a qualitative label."""
    if high >= 75:
        return 'Hot'
    if low <= 25:
        return 'Cold'
    if close > 50:
        return 'Warm'
    if close > 25:
        return 'Lukewarm'
    return 'Cold'


def classify_buying_signal(nhnl_momentum, ncfd_label):
    """
    NHNL momentum × NCFD label → buying opportunity signal.
    Returns: 'Late Buying' | '50/50 Buying' | 'Early Buying' | None
    """
    if nhnl_momentum is None or ncfd_label is None:
        return None
    table = {
        ('Hot',  'Hot'):      'Late Buying',
        ('Hot',  'Warm'):     'Late Buying',
        ('Hot',  'Lukewarm'): '50/50 Buying',
        ('Hot',  'Cold'):     'Early Buying',
        ('Cold', 'Hot'):      'Late Buying',
        ('Cold', 'Warm'):     '50/50 Buying',
        ('Cold', 'Lukewarm'): 'Early Buying',
        ('Cold', 'Cold'):     'Early Buying',
    }
    return table.get((nhnl_momentum, ncfd_label))


def classify_nhnl(nhnl_history, higq, lowq):
    """
    Return three independent NHNL conditions:
      momentum  — 'Hot' | 'Cold' | None
      highs     — True if HIGQ >= 100
      lows      — True if LOWQ >= 50
    nhnl_history[0] = today, [1] = yesterday, [2] = day before.
    """
    nhnl_today = nhnl_history[0]
    yesterday  = nhnl_history[1] if len(nhnl_history) > 1 else None

    if nhnl_today >= 150 or (yesterday is not None and nhnl_today - yesterday >= 100):
        momentum = 'Hot'
    elif len(nhnl_history) >= 3 and all(v < 0 for v in nhnl_history[:3]):
        momentum = 'Cold'
    else:
        momentum = None

    return momentum, higq >= 100, lowq >= 50


def main():
    print("Fetching SPX and EMAs via yfinance...", flush=True)
    spx, ema12, ema25 = fetch_spx()

    print("Fetching MMTH via Barchart...", flush=True)
    mmth = fetch_mmth()

    print("Fetching NCFD via Barchart...", flush=True)
    ncfd_close, ncfd_high, ncfd_low = fetch_ncfd()
    ncfd_label = classify_ncfd(ncfd_close, ncfd_high, ncfd_low)
    print(f"  NCFD label: {ncfd_label}", flush=True)

    print("Fetching HIGQ via Barchart...", flush=True)
    higq = fetch_barchart_last(BC_URL_HIGQ, '$HIGQ')

    print("Fetching LOWQ via Barchart...", flush=True)
    lowq = fetch_barchart_last(BC_URL_LOWQ, '$LOWQ')

    nhnl_today = round(higq - lowq, 2)
    print(f"  NHNL: {nhnl_today} (HIGQ={higq:.0f}, LOWQ={lowq:.0f})", flush=True)

    regime_class, regime_div, regime_cond = classify(spx, ema12, mmth)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Preserve regime_since and NHNL history from previous run
    out_path         = os.path.abspath(OUTPUT_PATH)
    regime_since     = today
    old_nhnl_history = []
    if os.path.exists(out_path):
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                prev = json.load(f)
            if prev.get("regime_class") == regime_class:
                regime_since = prev.get("regime_since", today)
            old_nhnl_history = prev.get("nhnl_history", [])
        except Exception:
            pass

    nhnl_history     = [nhnl_today] + old_nhnl_history[:2]
    nhnl_momentum, nhnl_highs, nhnl_lows = classify_nhnl(nhnl_history, higq, lowq)
    parts = [p for p in [nhnl_momentum, 'Highs' if nhnl_highs else None, 'Lows' if nhnl_lows else None] if p]
    print(f"  NHNL: {' · '.join(parts) if parts else 'Neutral'}", flush=True)

    buying_signal = classify_buying_signal(nhnl_momentum, ncfd_label)
    print(f"  Buying signal: {buying_signal}", flush=True)

    output = {
        "updated":        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "spx":            round(spx, 2),
        "ema12":          round(ema12, 2),
        "ema25":          round(ema25, 2),
        "mmth":           round(mmth, 2),
        "ncfd":           ncfd_close,
        "ncfd_high":      ncfd_high,
        "ncfd_low":       ncfd_low,
        "ncfd_label":     ncfd_label,
        "higq":           higq,
        "lowq":           lowq,
        "nhnl":           nhnl_today,
        "nhnl_history":   nhnl_history,
        "nhnl_momentum":  nhnl_momentum,
        "nhnl_highs":     nhnl_highs,
        "nhnl_lows":      nhnl_lows,
        "buying_signal":  buying_signal,
        "regime_class":   regime_class,
        "regime_div":     regime_div,
        "regime_since":   regime_since,
        "regime_cond":    regime_cond,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, separators=(",", ":"))

    print(f"  Regime: {regime_class.upper()} ({regime_div}) since {regime_since}", flush=True)
    print(f"  Written: {out_path}", flush=True)


if __name__ == "__main__":
    main()
