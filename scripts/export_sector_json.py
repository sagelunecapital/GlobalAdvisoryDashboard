#!/usr/bin/env python3
"""
Export the latest sector rotation data to prototypes/sector_rotation.json
for consumption by the Global Advisory Dashboard.
"""
import json
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_F     = BASE_DIR / "Sector Rotation" / "sector_rotation.db"
OUT_F    = BASE_DIR / "prototypes" / "sector_rotation.json"
LEAD_F   = BASE_DIR / "prototypes" / "leadership.json"

LOOKBACK_2M        = 42            # trading days ~ 2 months, for the "new high" test
LEAD_HISTORY_START = "2026-06-01"  # earliest day to emit a daily Leadership snapshot


def country_of(group_id: str) -> str:
    if group_id.startswith("United States"):
        return "United States"
    if group_id.startswith("China"):
        return "China"
    return group_id.split()[0]


def leadership_cat(px, ema25, atr, hi2m):
    """4-bucket Leadership classification (Leading overrides the band).
      Leading      px > 2-month prior high (new high)
      Bounced Off  px > ema25 + atr
      Found Ground ema25 - atr <= px <= ema25 + atr
      Lost Ground  px < ema25 - atr
    """
    if px is None or ema25 is None or atr is None:
        return None
    if hi2m is not None and px > hi2m:
        return "leading"
    if px > ema25 + atr:
        return "bouncedOff"
    if px < ema25 - atr:
        return "lostGround"
    return "foundGround"


def build_leadership_history(conn, start_date: str) -> dict:
    """Per-day algorithmic Leadership snapshots (US groups) from start_date onward.

    For each trading day, classify each US industry exactly like the live
    lead_cat (index vs 25d EMA +/-1 ATR, with a new 2-month high = Leading),
    using that day's own EMA/ATR and the 2-month high as of that day.
    """
    from itertools import groupby
    rows = conn.execute(
        "SELECT group_id, date, index_level, ema_25_idx, atr_14 FROM group_rs "
        "WHERE group_id LIKE 'United States %' ORDER BY group_id, date"
    ).fetchall()

    snapshots: dict = {}
    for gid, grp in groupby(rows, key=lambda r: r["group_id"]):
        name   = gid.replace("United States ", "")
        g      = list(grp)
        levels = [r["index_level"] for r in g]
        for i, r in enumerate(g):
            d = r["date"]
            if d < start_date:
                continue
            prior = [x for x in levels[max(0, i - LOOKBACK_2M):i] if x is not None]
            hi2m  = max(prior) if prior else None
            cat   = leadership_cat(r["index_level"], r["ema_25_idx"], r["atr_14"], hi2m)
            if not cat:
                continue
            snapshots.setdefault(
                d, {"lostGround": [], "foundGround": [], "bouncedOff": [], "leading": []}
            )[cat].append(name)

    for d in snapshots:
        for k in snapshots[d]:
            snapshots[d][k].sort()
    return snapshots


def main() -> None:
    if not DB_F.exists():
        print(f"[warn] DB not found: {DB_F}")
        return

    conn = sqlite3.connect(DB_F)
    conn.row_factory = sqlite3.Row

    latest = conn.execute("SELECT MAX(date) FROM group_rs").fetchone()[0]
    if not latest:
        print("[warn] group_rs is empty — nothing to export.")
        conn.close()
        return

    # group_summary may not exist on the first run (created by sector_data_collector.py)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "group_summary" in tables:
        sum_join  = "LEFT JOIN group_summary s ON r.group_id = s.group_id AND r.date = s.date"
        sum_cols  = "s.rs_rank_daily, s.rs_rank_weekly, s.rs_rank_monthly, s.perf_1d, s.perf_5d, s.perf_10d, s.perf_1m, s.perf_2m, s.perf_3m"
    else:
        sum_join  = ""
        sum_cols  = "NULL AS rs_rank_daily,NULL AS rs_rank_weekly,NULL AS rs_rank_monthly,NULL AS perf_1d,NULL AS perf_5d,NULL AS perf_10d,NULL AS perf_1m,NULL AS perf_2m,NULL AS perf_3m"
        print("[warn] group_summary table not found — run sector_data_collector.py first.")

    # Tickers per group (reconstruct group_id using the same display-name logic)
    ticker_rows = conn.execute("""
        SELECT
            country || ' ' || industry ||
                CASE WHEN TRIM(COALESCE(sub_industry,'')) != ''
                     THEN ': ' || TRIM(sub_industry)
                     ELSE ''
                END AS gid,
            ticker
        FROM industry
        ORDER BY gid, ticker
    """).fetchall()
    ticker_map: dict = {}
    for gid, raw_ticker in ticker_rows:
        # For China/Korea the raw ticker may be "123456 CompanyName" — keep just the code
        clean = raw_ticker.split()[0] if raw_ticker else raw_ticker
        ticker_map.setdefault(gid, []).append(clean)

    # 2-month prior high of the index per group (excludes the latest bar, so
    # "px > hi_2m" means a genuine new high vs the prior ~2 months).
    hist = conn.execute(
        "SELECT group_id, index_level FROM group_rs ORDER BY group_id, date"
    ).fetchall()
    hi_2m_map: dict = {}
    _cur_gid, _levels = None, []
    def _flush(gid, levels):
        if gid is not None and len(levels) > 1:
            prior = levels[-(LOOKBACK_2M + 1):-1]   # exclude latest bar
            hi_2m_map[gid] = max(prior) if prior else None
    for gid, lvl in hist:
        if gid != _cur_gid:
            _flush(_cur_gid, _levels)
            _cur_gid, _levels = gid, []
        if lvl is not None:
            _levels.append(lvl)
    _flush(_cur_gid, _levels)

    # Daily algorithmic Leadership snapshots (baseline history for the tab/charts)
    lead_hist = build_leadership_history(conn, LEAD_HISTORY_START)

    # Each group is exported at its own latest date so that markets closing
    # at different times (HK ahead of US) don't produce synthetic zero-return
    # rows for groups whose constituent stocks haven't closed yet.
    rows = conn.execute(f"""
        SELECT
            r.group_id,
            r.date,
            r.index_level,
            r.rs,
            r.ema_21_rs,
            r.ema_25_idx,
            r.rs - r.ema_21_rs  AS rs_gap,
            r.rs_minus_ema,
            r.atr_14,
            r.atr_14_pct,
            {sum_cols}
        FROM group_rs r
        JOIN (
            SELECT group_id, MAX(date) AS max_date
            FROM group_rs
            GROUP BY group_id
        ) m ON r.group_id = m.group_id AND r.date = m.max_date
        {sum_join}
        ORDER BY r.group_id
    """).fetchall()

    conn.close()

    def _round(v, n=4):
        return round(float(v), n) if v is not None else None

    groups = []
    for r in rows:
        px    = _round(r["index_level"])
        ema25 = _round(r["ema_25_idx"], 4)
        atr   = _round(r["atr_14"], 4)
        hi2m  = _round(hi_2m_map.get(r["group_id"]), 4)
        groups.append({
            "group_id":       r["group_id"],
            "country":        country_of(r["group_id"]),
            "date":           r["date"],
            "index_level":    px,
            "rs":             _round(r["rs"], 6),
            "ema_21_rs":      _round(r["ema_21_rs"], 6),
            "ema_25_idx":     ema25,
            "rs_gap":         _round(r["rs_gap"], 6),
            "rs_minus_ema":   _round(r["rs_minus_ema"], 6),
            "atr_14":         atr,
            "atr_14_pct":     _round(r["atr_14_pct"], 4),
            "hi_2m":          hi2m,
            "lead_cat":       leadership_cat(px, ema25, atr, hi2m),
            "rs_rank_daily":  _round(r["rs_rank_daily"], 2),
            "rs_rank_weekly": _round(r["rs_rank_weekly"], 2),
            "rs_rank_monthly":_round(r["rs_rank_monthly"], 2),
            "perf_1d":        _round(r["perf_1d"], 4),
            "perf_5d":        _round(r["perf_5d"], 4),
            "perf_10d":       _round(r["perf_10d"], 4),
            "perf_1m":        _round(r["perf_1m"], 4),
            "perf_2m":        _round(r["perf_2m"], 4),
            "perf_3m":        _round(r["perf_3m"], 4),
            "tickers":        ticker_map.get(r["group_id"], []),
        })

    out = {"updated": latest, "groups": groups}
    with open(OUT_F, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))

    print(f"Exported {len(groups)} groups for {latest} -> {OUT_F.name}")

    lead_out = {"generated": latest, "start": LEAD_HISTORY_START, "snapshots": lead_hist}
    with open(LEAD_F, "w", encoding="utf-8") as f:
        json.dump(lead_out, f, separators=(",", ":"))
    print(f"Exported {len(lead_hist)} Leadership snapshots "
          f"({LEAD_HISTORY_START}..{latest}) -> {LEAD_F.name}")


if __name__ == "__main__":
    main()
