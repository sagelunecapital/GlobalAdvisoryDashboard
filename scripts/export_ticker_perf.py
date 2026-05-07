#!/usr/bin/env python3
"""
Export per-ticker performance & market-cap data for the Research tab.
Outputs prototypes/ticker_perf.json.
"""
import json
import sqlite3
from pathlib import Path

BASE_DIR = Path(r"P:\OneDrive\[03] Cowork")
DB_F     = BASE_DIR / "Sector Rotation" / "sector_rotation.db"
OUT_F    = BASE_DIR / "prototypes" / "ticker_perf.json"


def main() -> None:
    if not DB_F.exists():
        print(f"[warn] DB not found: {DB_F}")
        return

    conn = sqlite3.connect(DB_F)
    conn.row_factory = sqlite3.Row

    # ── Reference dates ──────────────────────────────────────────
    all_dates = [r[0] for r in conn.execute(
        "SELECT DISTINCT date FROM daily ORDER BY date"
    ).fetchall()]
    if not all_dates:
        print("[warn] daily table is empty")
        conn.close()
        return

    latest     = all_dates[-1]
    latest_idx = len(all_dates) - 1

    def date_back(n: int) -> str:
        return all_dates[max(0, latest_idx - n)]

    date_ytd = (
        conn.execute("SELECT MAX(date) FROM daily WHERE date<'2026-01-01'").fetchone()[0]
        or all_dates[0]
    )
    date_1d = date_back(1)
    date_5d = date_back(5)
    date_1m = date_back(21)
    date_6m = date_back(126)
    date_1y = date_back(252)

    needed = {latest, date_ytd, date_1d, date_5d, date_1m, date_6m, date_1y}

    # ── Build price lookup ────────────────────────────────────────
    ph = ",".join("?" * len(needed))
    prices: dict[str, dict[str, float]] = {}
    for row in conn.execute(
        f"SELECT yf_ticker, date, close FROM daily WHERE date IN ({ph})",
        list(needed),
    ).fetchall():
        prices.setdefault(row[0], {})[row[1]] = row[2]

    def perf(yf_tk: str, from_d: str, to_d: str):
        p = prices.get(yf_tk, {})
        f, t = p.get(from_d), p.get(to_d)
        if f and t and f > 0:
            return round((t / f - 1) * 100, 4)
        return None

    # ── Market caps (latest snapshot per ticker) ──────────────────
    mc_map: dict[str, float] = dict(conn.execute("""
        SELECT m.yf_ticker, m.market_cap
        FROM market_caps m
        JOIN (SELECT yf_ticker, MAX(date) AS md FROM market_caps GROUP BY yf_ticker) x
          ON m.yf_ticker=x.yf_ticker AND m.date=x.md
    """).fetchall())

    # ── Display-ticker map  (yf_ticker -> display ticker) ─────────
    name_map: dict[str, str] = {}
    for row in conn.execute("SELECT yf_ticker, ticker FROM industry").fetchall():
        name_map[row[0]] = row[1].split()[0]

    # ── SPX benchmark ────────────────────────────────────────────
    spx_ytd = perf("^GSPC", date_ytd, latest)

    # ── Per-ticker performance ────────────────────────────────────
    result: dict[str, dict] = {}
    for yf_tk, price_by_date in prices.items():
        if latest not in price_by_date:
            continue                    # no current price — skip
        disp = name_map.get(yf_tk, yf_tk)
        entry = {
            "perf_1d":  perf(yf_tk, date_1d,  latest),
            "perf_5d":  perf(yf_tk, date_5d,  latest),
            "perf_1m":  perf(yf_tk, date_1m,  latest),
            "perf_6m":  perf(yf_tk, date_6m,  latest),
            "perf_1y":  perf(yf_tk, date_1y,  latest),
            "perf_ytd": perf(yf_tk, date_ytd, latest),
            "mktcap":   mc_map.get(yf_tk),
        }
        result[disp] = entry
        if yf_tk != disp:              # alias so users can enter either form
            result[yf_tk] = entry

    conn.close()

    out = {"updated": latest, "spx_ytd": spx_ytd, "tickers": result}
    with open(OUT_F, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))

    print(f"Exported {len(result)} ticker keys for {latest} -> {OUT_F.name}")


if __name__ == "__main__":
    main()
