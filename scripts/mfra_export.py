#!/usr/bin/env python3
"""
mfra_export.py
Reads mfra_daily from sector_rotation.db and exports per-group
1D / 5D / 21D equal-weighted attribution to prototypes/mfra_group.json.

Run after mfra_compute.py.
"""

import json
import sqlite3
from pathlib import Path

import pandas as pd

DB_F  = Path(__file__).resolve().parent.parent / "Sector Rotation" / "sector_rotation.db"
OUT_F = Path(__file__).resolve().parent.parent / "prototypes" / "mfra_group.json"

PERIODS = {"1d": 1, "5d": 5, "21d": 21}


def main() -> None:
    conn = sqlite3.connect(DB_F)

    ind = pd.read_sql(
        "SELECT yf_ticker, ticker, country, industry, sub_industry FROM industry", conn
    )
    ind["sub_industry"] = ind["sub_industry"].fillna("")

    def leaf_gid(r):
        name = f"{r['country']} {r['industry']}"
        if r["sub_industry"].strip():
            name += f": {r['sub_industry'].strip()}"
        return name

    ind["group_id"] = ind.apply(leaf_gid, axis=1)
    ticker_label = ind.set_index("yf_ticker")["ticker"].to_dict()

    mfra = pd.read_sql(
        "SELECT yf_ticker, date, mkt_contrib, sec_contrib, sub_contrib, resid_contrib "
        "FROM mfra_daily ORDER BY date",
        conn,
    )
    conn.close()

    if mfra.empty:
        print("mfra_daily is empty — run mfra_compute.py first.")
        return

    mfra["date"] = pd.to_datetime(mfra["date"])

    pivots = {
        col: mfra.pivot(index="date", columns="yf_ticker", values=col)
        for col in ["mkt_contrib", "sec_contrib", "sub_contrib", "resid_contrib"]
    }
    all_dates = pivots["mkt_contrib"].index
    as_of = str(all_dates[-1].date())

    # group_id → [yf_ticker, ...]
    group_members: dict[str, list[str]] = (
        ind.groupby("group_id")["yf_ticker"].apply(list).to_dict()
    )

    result: dict = {"as_of": as_of, "groups": {}}

    for gid, yf_list in group_members.items():
        avail = [t for t in yf_list if t in pivots["mkt_contrib"].columns]
        if not avail:
            continue

        entry: dict = {}
        for pkey, n in PERIODS.items():
            wd = all_dates[-n:]

            def ew(col: str) -> float:
                return float(pivots[col][avail].loc[wd].sum().mean())

            gm = ew("mkt_contrib")
            gs = ew("sec_contrib")
            gu = ew("sub_contrib")
            gr = ew("resid_contrib")
            gt = gm + gs + gu + gr

            factors = {"mkt": gm, "sec": gs, "sub": gu, "resid": gr}
            driver  = max(factors, key=lambda k: abs(factors[k]))

            idio_tickers: list[str] = []
            if driver == "resid" and len(avail) > 1:
                resid_sums = pivots["resid_contrib"][avail].loc[wd].sum()
                threshold = abs(gr) * 0.20
                amplifying = resid_sums[
                    (resid_sums * gr > 0) & (resid_sums.abs() >= threshold)
                ].abs().nlargest(3).index.tolist()
                idio_tickers = [ticker_label.get(t, t) for t in amplifying]

            entry[pkey] = {
                "total": round(gt, 2),
                "mkt":   round(gm, 2),
                "sec":   round(gs, 2),
                "sub":   round(gu, 2),
                "resid": round(gr, 2),
                "driver": driver,
                "idio_tickers": idio_tickers,
            }

        result["groups"][gid] = entry

    with open(OUT_F, "w") as f:
        json.dump(result, f, separators=(",", ":"))

    print(f"Exported {len(result['groups'])} groups  as_of {as_of}  -> {OUT_F}")


if __name__ == "__main__":
    main()
