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

    # ── Supplemental ETF fetch (not in DB) ───────────────────────
    SUPP_ETFS = [
        "XLE","XLK","XLF","XLV","XLI","XLC","XLY","XLP","XLB","XLRE","XLU",
        "SPY","QQQ","IWM","DIA","VTI",
        "GLD","SLV","TLT","IEF","HYG","EMB","LQD",
        "VNQ","IBB","XBI","ICLN","LIT","COPX","PICK","URNM","WOOD","CPER",
        "ARKK","XME","XOP","OIH","KRE","IAT","SMH","SOXX",
    ]
    try:
        import yfinance as yf
        import pandas as pd
        # Download 1Y+ of data to cover all reference periods
        etf_raw = yf.download(
            SUPP_ETFS, start=date_1y, auto_adjust=True, progress=False
        )
        closes = etf_raw["Close"] if "Close" in etf_raw else etf_raw
        if isinstance(closes, pd.Series):
            closes = closes.to_frame(name=SUPP_ETFS[0])
        for etf in SUPP_ETFS:
            if etf not in closes.columns:
                continue
            s = closes[etf].dropna()
            if s.empty:
                continue
            def _get(d: str):
                idx = s.index[s.index <= pd.Timestamp(d)]
                return float(s[idx[-1]]) if len(idx) else None
            p_now = _get(latest)
            if p_now is None:
                continue
            def _ep(fd: str, td: str):
                pf, pt = _get(fd), _get(td)
                if pf and pt and pf > 0:
                    return round((pt / pf - 1) * 100, 4)
                return None
            result[etf] = {
                "perf_1d":  _ep(date_1d,  latest),
                "perf_5d":  _ep(date_5d,  latest),
                "perf_1m":  _ep(date_1m,  latest),
                "perf_6m":  _ep(date_6m,  latest),
                "perf_1y":  _ep(date_1y,  latest),
                "perf_ytd": _ep(date_ytd, latest),
                "mktcap":   None,
            }
        print(f"  +{sum(e in result for e in SUPP_ETFS)} ETF tickers added")
    except Exception as exc:
        print(f"[warn] ETF supplemental fetch skipped: {exc}")

    # ── Watchlist tickers (user-defined, not in DB) ───────────────
    WATCHLIST_F = BASE_DIR / "research_watchlist.json"
    if WATCHLIST_F.exists():
        try:
            import yfinance as yf
            import pandas as pd
            raw_list = json.loads(WATCHLIST_F.read_text(encoding="utf-8"))
            # Normalize: uppercase, dots→dashes (yfinance format)
            def _norm(t: str) -> str:
                return t.strip().upper().replace(".", "-")
            wl = [_norm(t) for t in raw_list if t.strip()]
            missing = [t for t in wl if t not in result]
            if missing:
                wl_raw = yf.download(
                    missing, start=date_1y, auto_adjust=True, progress=False
                )
                wl_closes = wl_raw["Close"] if "Close" in wl_raw else wl_raw
                if isinstance(wl_closes, pd.Series):
                    wl_closes = wl_closes.to_frame(name=missing[0])
                added = 0
                for tk in missing:
                    if tk not in wl_closes.columns:
                        continue
                    s = wl_closes[tk].dropna()
                    if s.empty:
                        continue
                    def _gwl(d: str, _s=s) -> float | None:
                        idx = _s.index[_s.index <= pd.Timestamp(d)]
                        return float(_s[idx[-1]]) if len(idx) else None
                    if _gwl(latest) is None:
                        continue
                    def _epwl(fd: str, td: str, _g=_gwl) -> float | None:
                        pf, pt = _g(fd), _g(td)
                        return round((pt / pf - 1) * 100, 4) if pf and pt and pf > 0 else None
                    mc = None
                    try:
                        fi = yf.Ticker(tk).fast_info
                        mc = float(fi.market_cap) if fi.market_cap else None
                    except Exception:
                        pass
                    result[tk] = {
                        "perf_1d":  _epwl(date_1d,  latest),
                        "perf_5d":  _epwl(date_5d,  latest),
                        "perf_1m":  _epwl(date_1m,  latest),
                        "perf_6m":  _epwl(date_6m,  latest),
                        "perf_1y":  _epwl(date_1y,  latest),
                        "perf_ytd": _epwl(date_ytd, latest),
                        "mktcap":   mc,
                    }
                    added += 1
                print(f"  +{added}/{len(missing)} watchlist tickers added")
            else:
                print(f"  Watchlist: all {len(wl)} tickers already tracked")
        except Exception as exc:
            print(f"[warn] Watchlist fetch skipped: {exc}")

    out = {"updated": latest, "spx_ytd": spx_ytd, "tickers": result}
    with open(OUT_F, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))

    print(f"Exported {len(result)} ticker keys for {latest} -> {OUT_F.name}")


if __name__ == "__main__":
    main()
