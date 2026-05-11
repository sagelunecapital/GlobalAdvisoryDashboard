# -*- coding: utf-8 -*-
"""
Fetch 3 years of daily OHLC from yfinance for COT contracts.
Exports to prototypes/price_data.json.
Run after export_cot_json.py to refresh price data.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import yfinance as yf

OUT_PATH = Path(__file__).parent.parent / "prototypes" / "price_data.json"

TICKER_MAP = {
    "067651": "CL=F",
    "111659": "RB=F",
    "023651": "NG=F",
    "088691": "GC=F",
    "084691": "SI=F",
    "085692": "HG=F",
    "075651": "PA=F",
    "076651": "PL=F",
    "191693": "ALI=F",
    "189691": "LTH=F",
    "002602": "ZC=F",
    "005602": "ZS=F",
    "001602": "ZW=F",
    "073732": "CC=F",
    "083731": "KC=F",
    "033661": "CT=F",
    "080732": "SB=F",
    "054642": "HE=F",
    "057642": "LE=F",
    "099741": "6E=F",
    "096742": "6B=F",
    "097741": "6J=F",
    "090741": "6C=F",
    "232741": "6A=F",
    "092741": "6S=F",
    "098662": "DX-Y.NYB",
    "020601": "ZB=F",
    "043602": "ZN=F",
    "044601": "ZF=F",
    "042601": "ZT=F",
    "13874A": "ES=F",
    "209742": "NQ=F",
    "239742": "RTY=F",
    "12460+": "YM=F",
    "133742": "BTC=F",
}

end   = datetime.today()
start = end - timedelta(days=365 * 11)  # cover full COT history (~500 weeks back to ~2015)

out = {}
for code, ticker in TICKER_MAP.items():
    print(f"  {ticker:<12}", end="")
    try:
        df = yf.download(
            ticker,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval="1d",
            progress=False,
            auto_adjust=True,
        )
        if df.empty:
            print("no data")
            continue
        # Flatten MultiIndex columns if present
        if hasattr(df.columns, "levels"):
            df.columns = df.columns.get_level_values(0)
        out[code] = {
            "ticker": ticker,
            "dates":  [d.strftime("%Y-%m-%d") for d in df.index],
            "open":   [round(float(v), 6) for v in df["Open"]],
            "high":   [round(float(v), 6) for v in df["High"]],
            "low":    [round(float(v), 6) for v in df["Low"]],
            "close":  [round(float(v), 6) for v in df["Close"]],
        }
        print(f"{len(df)} rows")
    except Exception as e:
        print(f"error: {e}")

with open(OUT_PATH, "w", encoding="utf-8") as f:
    json.dump(out, f, separators=(",", ":"))

size_kb = OUT_PATH.stat().st_size / 1024
print(f"\nExported {len(out)} tickers -> {OUT_PATH} ({size_kb:.0f} KB)")
