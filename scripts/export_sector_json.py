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


def country_of(group_id: str) -> str:
    if group_id.startswith("United States"):
        return "United States"
    if group_id.startswith("China"):
        return "China"
    return group_id.split()[0]


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
            r.rs - r.ema_21_rs  AS rs_gap,
            r.rs_minus_ema,
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
        groups.append({
            "group_id":       r["group_id"],
            "country":        country_of(r["group_id"]),
            "date":           r["date"],
            "index_level":    _round(r["index_level"]),
            "rs":             _round(r["rs"], 6),
            "ema_21_rs":      _round(r["ema_21_rs"], 6),
            "rs_gap":         _round(r["rs_gap"], 6),
            "rs_minus_ema":   _round(r["rs_minus_ema"], 6),
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


if __name__ == "__main__":
    main()
