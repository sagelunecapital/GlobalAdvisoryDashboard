#!/usr/bin/env python3
"""screener_weekly.py - add Fri-to-Fri weekly returns to the screener movers JSON.

The weekly movers view consolidates each ticker to one row per Mon-Fri week and
shows its true weekly return (this Friday's close vs last Friday's close) rather
than the per-day change_pct. Mover rows carry no price, so the returns are
computed here from yfinance daily closes and written back as:

    "weekly_returns": { "<week-monday>": { "<ticker>": <pct>, ... }, ... }

into prototypes/screener_movers.json (US) and screener_movers_cn.json (HK/CN).
Idempotent: recomputed for every week present in by_date on each run. Tickers
that don't resolve on yfinance are skipped (the UI falls back to daily change).

Run after screener enrichment / screener_fetch.py.
"""
import json, sys, os
from datetime import date, timedelta
import bisect

import yfinance as yf

HERE  = os.path.dirname(os.path.abspath(__file__))
PROTO = os.path.normpath(os.path.join(HERE, "..", "prototypes"))


def yf_us(t):
    return t.replace(".", "-")           # UHAL.B -> UHAL-B


def yf_hk(t):
    try:
        return "%04d.HK" % int(t)        # 1651 -> 1651.HK
    except ValueError:
        return t


def week_monday(iso):
    d = date.fromisoformat(iso)
    return d - timedelta(days=d.weekday())


def tickers_in_week(by_date, mon):
    days = {(mon + timedelta(days=i)).isoformat() for i in range(5)}
    out = set()
    for k, rows in by_date.items():
        if k in days:
            for r in rows:
                out.add(r["ticker"])
    return out


def download_closes(symbols, start, end):
    """Return {symbol: (sorted_dates[], closes[])} of daily closes."""
    closes = {}
    CH = 100
    for i in range(0, len(symbols), CH):
        chunk = symbols[i:i + CH]
        try:
            df = yf.download(chunk, start=start, end=end, interval="1d",
                             auto_adjust=True, progress=False,
                             group_by="ticker", threads=True)
        except Exception as e:
            print("[weekly] download chunk failed: %s" % e, flush=True)
            continue
        if df is None or len(df) == 0:
            continue
        multi = hasattr(df.columns, "levels") and len(df.columns.levels) > 1
        for s in chunk:
            try:
                col = df[s]["Close"] if multi else df["Close"]
            except Exception:
                continue
            col = col.dropna()
            if len(col) == 0:
                continue
            ds = [ix.date().isoformat() for ix in col.index]
            vs = [float(v) for v in col.values]
            closes[s] = (ds, vs)
    return closes


def close_on_or_before(series, target, tol_days=7):
    """Last close at or before `target`, within tol_days (else None)."""
    if not series:
        return None
    ds, vs = series
    i = bisect.bisect_right(ds, target) - 1
    if i < 0:
        return None
    found = ds[i]
    if (date.fromisoformat(target) - date.fromisoformat(found)).days > tol_days:
        return None
    return vs[i]


def build(path, symfn, ensure_ascii):
    if not os.path.exists(path):
        print("[weekly] missing %s - skip" % path, flush=True)
        return
    data = json.loads(open(path, encoding="utf-8").read())
    by_date = data.get("by_date", {})
    if not by_date:
        return

    tickers = sorted({r["ticker"] for rows in by_date.values() for r in rows})
    sym = {t: symfn(t) for t in tickers}
    all_dates = sorted(by_date)
    start = (date.fromisoformat(all_dates[0]) - timedelta(days=14)).isoformat()
    end   = (date.fromisoformat(all_dates[-1]) + timedelta(days=4)).isoformat()

    closes = download_closes(sorted(set(sym.values())), start, end)

    weeks = sorted({week_monday(k) for k in by_date})
    weekly, missing = {}, set()
    for mon in weeks:
        fri  = (mon + timedelta(days=4)).isoformat()
        pfri = (mon - timedelta(days=3)).isoformat()
        row = {}
        for t in tickers_in_week(by_date, mon):
            s = closes.get(sym[t])
            cf = close_on_or_before(s, fri)
            cp = close_on_or_before(s, pfri)
            if cf and cp and cp != 0:
                row[t] = round((cf / cp - 1) * 100, 2)
            else:
                missing.add(t)
        if row:
            weekly[mon.isoformat()] = row

    data["weekly_returns"] = weekly
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=ensure_ascii)

    resolved = sum(len(v) for v in weekly.values())
    print("[weekly] %s: %d weeks, %d ticker-week returns, %d tickers unresolved"
          % (os.path.basename(path), len(weekly), resolved, len(missing)), flush=True)
    if missing:
        print("[weekly]   unresolved (fallback to daily): %s"
              % ", ".join(sorted(missing)[:25]) + (" ..." if len(missing) > 25 else ""), flush=True)


def main():
    build(os.path.join(PROTO, "screener_movers.json"),    yf_us, ensure_ascii=True)
    build(os.path.join(PROTO, "screener_movers_cn.json"), yf_hk, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
