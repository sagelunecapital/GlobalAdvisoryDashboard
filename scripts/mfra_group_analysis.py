#!/usr/bin/env python3
"""
mfra_group_analysis.py
Aggregate individual-ticker MFRA results for a given industry group.

Shows:
  1. Cumulative attribution per ticker
  2. Equal-weighted group aggregate
  3. Rolling 5d group + cross-sectional dispersion of individual returns
  4. Top idio-driven days (one ticker's residual dominates the group move)

Usage:
  python scripts/mfra_group_analysis.py [country] [industry]
  e.g.  python scripts/mfra_group_analysis.py "United States" LIDAR
"""

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DB_F = Path(__file__).resolve().parent.parent / "Sector Rotation" / "sector_rotation.db"

ROLL_WINDOW   = 5    # days for rolling view
IDIO_THRESH   = 0.40 # single ticker resid > X% of group total = idio-driven day
TOP_EVENTS    = 25


def run(country: str, industry: str) -> None:
    conn = sqlite3.connect(DB_F)

    # -- Get tickers + market caps -------------------------------------------
    tickers_df = pd.read_sql("""
        SELECT i.ticker, i.yf_ticker, i.sub_industry, mc.market_cap
        FROM industry i
        LEFT JOIN (
            SELECT yf_ticker, market_cap FROM market_caps
            WHERE date = (SELECT MAX(date) FROM market_caps)
        ) mc ON mc.yf_ticker = i.yf_ticker
        WHERE i.country = ? AND i.industry = ?
    """, conn, params=[country, industry])

    if tickers_df.empty:
        print(f"No tickers found for country='{country}' industry='{industry}'")
        conn.close()
        return

    yf_tickers = tickers_df["yf_ticker"].tolist()
    mc_map = tickers_df.set_index("yf_ticker")["market_cap"].fillna(0).to_dict()
    total_mc = sum(mc_map.values()) or 1.0

    print(f"\nGroup: {country} / {industry}  ({len(yf_tickers)} tickers)")

    # -- Pull mfra_daily for these tickers ------------------------------------
    ph  = ",".join(["?"] * len(yf_tickers))
    raw = pd.read_sql(
        f"SELECT yf_ticker, date, mkt_contrib, sec_contrib, sub_contrib, resid_contrib "
        f"FROM mfra_daily WHERE yf_ticker IN ({ph}) ORDER BY date",
        conn, params=yf_tickers,
    )
    conn.close()

    if raw.empty:
        print("No mfra_daily rows found — run mfra_compute.py first.")
        return

    raw["date"]  = pd.to_datetime(raw["date"])
    raw["total"] = raw[["mkt_contrib", "sec_contrib", "sub_contrib", "resid_contrib"]].sum(axis=1)

    # Pivot: rows = date, cols = ticker
    def pvt(col):
        return raw.pivot(index="date", columns="yf_ticker", values=col)

    p_mkt = pvt("mkt_contrib")
    p_sec = pvt("sec_contrib")
    p_sub = pvt("sub_contrib")
    p_res = pvt("resid_contrib")
    p_tot = pvt("total")
    dates = p_tot.index

    # Ticker label map  (yf_ticker -> display ticker)
    label = tickers_df.set_index("yf_ticker")["ticker"].to_dict()

    # ── 1. Multi-period snapshot (group equal-weighted) ----------------------
    last_date = dates[-1]
    ytd_start = pd.Timestamp(f"{last_date.year}-01-01")

    periods = [
        ("1D",   1),
        ("5D",   5),
        ("21D",  21),
        ("63D",  63),
        ("YTD",  None),   # None = use ytd_start
    ]

    def window_slice(n, ytd=False):
        if ytd:
            return dates[dates >= ytd_start]
        return dates[-n:]

    print()
    print("=" * 75)
    print(f"GROUP ATTRIBUTION SNAPSHOT  (equal-weighted, pp)  as of {last_date.date()}")
    print(f"{'Period':<6} {'Total':>7} {'Mkt':>7} {'Sector':>7} {'Sub':>7} {'Resid':>7}  Dom. factor")
    print("-" * 75)
    for period_label, n in periods:
        wd  = window_slice(n) if n else window_slice(None, ytd=True)
        gm  = p_mkt.loc[wd].sum().mean()
        gs  = p_sec.loc[wd].sum().mean()
        gu  = p_sub.loc[wd].sum().mean()
        gr  = p_res.loc[wd].sum().mean()
        gt  = gm + gs + gu + gr
        components = {"Mkt": gm, "Sector": gs, "Sub": gu, "Resid": gr}
        dom = max(components, key=lambda k: abs(components[k]))
        print(f"{period_label:<6} {gt:>7.2f} {gm:>7.2f} {gs:>7.2f} {gu:>7.2f} {gr:>7.2f}  {dom} ({components[dom]:+.2f}pp)")

    # ── 2. Per-ticker attribution for selected periods -----------------------
    print()
    print("=" * 75)
    for period_label, n in periods:
        wd = window_slice(n) if n else window_slice(None, ytd=True)
        print(f"PER TICKER  [{period_label}]  sorted by total return")
        print(f"  {'':6} {'Total':>7} {'Mkt':>7} {'Sector':>7} {'Sub':>7} {'Resid':>7}  MC Wt")
        rows = []
        for t in yf_tickers:
            tot = p_tot[t].loc[wd].sum()
            mkt = p_mkt[t].loc[wd].sum()
            sec = p_sec[t].loc[wd].sum()
            sub = p_sub[t].loc[wd].sum()
            res = p_res[t].loc[wd].sum()
            wt  = mc_map.get(t, 0) / total_mc * 100
            rows.append((label.get(t, t), tot, mkt, sec, sub, res, wt))
        for lbl, tot, mkt, sec, sub, res, wt in sorted(rows, key=lambda x: -x[1]):
            print(f"  {lbl:<6} {tot:>7.2f} {mkt:>7.2f} {sec:>7.2f} {sub:>7.2f} {res:>7.2f}  {wt:.1f}%")
        print()

    # ── 3. Rolling N-day group + dispersion ----------------------------------
    print()
    print("=" * 75)
    print(f"{ROLL_WINDOW}-DAY ROLLING  (last 20 bars, equal-weighted)  +  cross-sectional dispersion")
    print(f"{'Date':<12} {'GrpTot':>7} {'Mkt':>6} {'Sect':>6} {'Sub':>6} {'Resid':>6}  "
          f"{'Disp':>6}  Top idio name")
    print("-" * 75)

    for i in range(20):
        idx = len(dates) - 20 + i
        sl  = slice(max(0, idx - ROLL_WINDOW + 1), idx + 1)
        wd  = dates[sl]

        gm = p_mkt.loc[wd].sum().mean()
        gs = p_sec.loc[wd].sum().mean()
        gu = p_sub.loc[wd].sum().mean()
        gr = p_res.loc[wd].sum().mean()
        gt = gm + gs + gu + gr

        # Cross-sectional std of individual 5d total returns (dispersion proxy)
        ind_tot  = p_tot.loc[wd].sum()
        cs_std   = ind_tot.std()

        # Dominant single-name resid over the window
        resid_wd = p_res.loc[wd].sum()
        top_t    = resid_wd.abs().idxmax()
        top_lbl  = label.get(top_t, top_t)
        top_v    = resid_wd[top_t]
        conc     = abs(top_v) / (abs(gt) + 0.05) * 100

        dt_str = str(dates[idx].date())
        flag   = "*" if conc > IDIO_THRESH * 100 else " "
        print(f"{dt_str:<12} {gt:>7.2f} {gm:>6.2f} {gs:>6.2f} {gu:>6.2f} {gr:>6.2f}  "
              f"{cs_std:>5.1f}pp{flag} {top_lbl} {top_v:+.1f}pp ({conc:.0f}%)")

    # ── 4. Top idio-driven daily events -------------------------------------
    print()
    print("=" * 75)
    print(f"TOP IDIO-DRIVEN DAYS  (single ticker residual > {IDIO_THRESH*100:.0f}% of group daily move)")
    print(f"{'Date':<12} {'GrpTot':>7}  {'Name':<6}  {'Resid':>8}  {'Conc':>6}  Factor context")
    print("-" * 75)

    daily_grp = p_tot.mean(axis=1)
    dom_name  = p_res.abs().idxmax(axis=1)
    dom_val   = pd.Series(
        [p_res.loc[d, dom_name[d]] for d in p_res.index], index=p_res.index
    )
    conc_d    = dom_val.abs() / (daily_grp.abs() + 0.05)
    events    = conc_d[conc_d > IDIO_THRESH].sort_values(ascending=False).head(TOP_EVENTS)

    for dt, cv in events.items():
        nm   = dom_name[dt]
        lbl2 = label.get(nm, nm)
        rv   = p_res.loc[dt, nm]
        gv   = daily_grp[dt]
        # Group-level factor breakdown on that day
        gm_d = p_mkt.loc[dt].mean()
        gs_d = p_sec.loc[dt].mean()
        gu_d = p_sub.loc[dt].mean()
        context = f"mkt {gm_d:+.2f} sec {gs_d:+.2f} sub {gu_d:+.2f}"
        print(f"{str(dt.date()):<12} {gv:>7.2f}   {lbl2:<6}  {rv:>+8.2f}pp  {cv*100:>5.0f}%  {context}")


if __name__ == "__main__":
    if len(sys.argv) == 3:
        _country  = sys.argv[1]
        _industry = sys.argv[2]
    else:
        _country  = "United States"
        _industry = "LIDAR"
    run(_country, _industry)
