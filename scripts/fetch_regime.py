#!/usr/bin/env python3
"""
Fetch S&P 500 Market Regime data and write prototypes/regime.json.

Sources:
  - SPX price + EMA(10,20,30): yfinance (^GSPC daily closes)
  - MMTH (% NYSE stocks above 200d MA): Barchart overview page (lastPrice in embedded JSON)

Derived:
  - 25d EMA  = (EMA20 + EMA30) / 2
  - 12d EMA  = (2*EMA10 - 0.523*(EMA10 - EMA20)) / 2

Regime:
  - GREEN  : SPX >= EMA12 and MMTH >= 60
  - YELLOW : SPX >= EMA12 and MMTH <  60  (bearish breadth divergence)
           OR SPX <  EMA12 and MMTH >= 60  (bullish breadth divergence)
  - RED    : SPX <  EMA12 and MMTH <  60
"""

import json
import os
import re
from datetime import datetime, timezone

import requests
import yfinance as yf

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
OUTPUT_PATH = os.path.join(SCRIPT_DIR, "..", "prototypes", "regime.json")

BC_URL     = "https://www.barchart.com/stocks/quotes/$MMTH/overview"
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


def fetch_spx():
    ticker = yf.Ticker("^GSPC")
    hist   = ticker.history(period="90d")
    if hist.empty:
        raise ValueError("No SPX history returned by yfinance")
    close = hist["Close"]
    spx   = float(close.iloc[-1])
    e10   = float(close.ewm(span=10, adjust=False).mean().iloc[-1])
    e20   = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
    e30   = float(close.ewm(span=30, adjust=False).mean().iloc[-1])
    ema25 = (e20 + e30) / 2
    ema12 = (2 * e10 - 0.523 * (e10 - e20)) / 2
    print(f"  SPX: {spx:.2f}", flush=True)
    print(f"  EMA10: {e10:.2f}  EMA20: {e20:.2f}  EMA30: {e30:.2f}", flush=True)
    print(f"  12d EMA (derived): {ema12:.2f}  25d EMA (derived): {ema25:.2f}", flush=True)
    return spx, round(ema12, 2), round(ema25, 2)


def fetch_mmth():
    r = requests.get(BC_URL, headers=BC_HEADERS, timeout=30)
    r.raise_for_status()
    m = re.search(r'"lastPrice"\s*:\s*"([0-9]+(?:\.[0-9]+)?)"', r.text)
    if not m:
        raise ValueError("Could not find lastPrice for $MMTH in Barchart HTML")
    mmth = float(m.group(1))
    print(f"  MMTH: {mmth:.2f}", flush=True)
    return round(mmth, 2)


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


def main():
    print("Fetching SPX and EMAs via yfinance...", flush=True)
    spx, ema12, ema25 = fetch_spx()

    print("Fetching MMTH via Barchart...", flush=True)
    mmth = fetch_mmth()

    regime_class, regime_div, regime_cond = classify(spx, ema12, mmth)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Preserve regime_since — only reset when the regime class changes
    out_path     = os.path.abspath(OUTPUT_PATH)
    regime_since = today
    if os.path.exists(out_path):
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                prev = json.load(f)
            if prev.get("regime_class") == regime_class:
                regime_since = prev.get("regime_since", today)
        except Exception:
            pass

    output = {
        "updated":      datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "spx":          round(spx, 2),
        "ema12":        round(ema12, 2),
        "ema25":        round(ema25, 2),
        "mmth":         round(mmth, 2),
        "regime_class": regime_class,
        "regime_div":   regime_div,
        "regime_since": regime_since,
        "regime_cond":  regime_cond,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, separators=(",", ":"))

    print(f"  Regime: {regime_class.upper()} ({regime_div}) since {regime_since}", flush=True)
    print(f"  Written: {out_path}", flush=True)


if __name__ == "__main__":
    main()
