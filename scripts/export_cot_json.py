# -*- coding: utf-8 -*-
"""
Export CFTC COT data from SQLite to prototypes/cot_data.json
Run after cot_report_pull.py to refresh dashboard data.
"""

import json
import sqlite3
from pathlib import Path

DB_PATH  = Path(__file__).parent.parent / "data" / "cftc_cot.db"
OUT_PATH = Path(__file__).parent.parent / "prototypes" / "cot_data.json"

DISPLAY_NAMES = {
    "067651": "Crude Oil (WTI)",
    "111659": "Gasoline (RBOB)",
    "023651": "Natural Gas",
    "088691": "Gold",
    "084691": "Silver",
    "085692": "Copper",
    "075651": "Palladium",
    "076651": "Platinum",
    "191693": "Aluminum",
    "189691": "Lithium Hydroxide",
    "002602": "Corn",
    "005602": "Soybeans",
    "001602": "Wheat (SRW)",
    "073732": "Cocoa",
    "083731": "Coffee C",
    "033661": "Cotton No. 2",
    "054642": "Lean Hogs",
    "057642": "Live Cattle",
    "080732": "Sugar No. 11",
    "099741": "Euro FX",
    "096742": "British Pound",
    "097741": "Japanese Yen",
    "090741": "Canadian Dollar",
    "232741": "Australian Dollar",
    "092741": "Swiss Franc",
    "098662": "US Dollar Index",
    "020601": "Treasury Bonds (30Y)",
    "043602": "Treasury Notes (10Y)",
    "044601": "Treasury Notes (5Y)",
    "042601": "Treasury Notes (2Y)",
    "13874A": "E-Mini S&P 500",
    "209742": "Nasdaq Mini",
    "239742": "E-Mini Russell 2000",
    "12460+": "DJIA",
    "133741": "Bitcoin",
    "133742": "Micro Bitcoin",
}

CLASS_MAP = {
    "Energy":      ["067651", "111659", "023651"],
    "Metals":      ["088691", "084691", "085692", "075651", "076651", "191693", "189691"],
    "Agriculture": ["002602", "005602", "001602", "073732", "083731", "033661", "080732", "054642", "057642"],
    "Currencies":  ["099741", "096742", "097741", "090741", "232741", "092741", "098662"],
    "Bonds":       ["020601", "043602", "044601", "042601"],
    "Indices":     ["13874A", "209742", "239742", "12460+", "133741", "133742"],
}

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

out = {}
for cls, codes in CLASS_MAP.items():
    for code in codes:
        rows = conn.execute("""
            SELECT yyyy_report_week_ww, report_date,
                   MAX(CAST(open_interest_all          AS REAL)) AS oi,
                   AVG(CAST(comm_positions_long_all    AS REAL)) AS cl,
                   AVG(CAST(comm_positions_short_all   AS REAL)) AS cs,
                   AVG(CAST(noncomm_positions_long_all AS REAL)) AS nl,
                   AVG(CAST(noncomm_positions_short_all AS REAL)) AS ns
            FROM cot_legacy_futures
            WHERE cftc_contract_market_code = ?
            GROUP BY report_date
            ORDER BY report_date ASC
        """, (code,)).fetchall()

        if not rows:
            continue

        def r2i(v):
            return round(v) if v is not None else None

        out[code] = {
            "name":  DISPLAY_NAMES.get(code, code),
            "class": cls,
            "weeks": [r["yyyy_report_week_ww"] for r in rows],
            "oi":    [r2i(r["oi"]) for r in rows],
            "cl":    [r2i(r["cl"]) for r in rows],
            "cs":    [r2i(r["cs"]) for r in rows],
            "nl":    [r2i(r["nl"]) for r in rows],
            "ns":    [r2i(r["ns"]) for r in rows],
        }

conn.close()

with open(OUT_PATH, "w", encoding="utf-8") as f:
    json.dump(out, f, separators=(",", ":"))

size_kb = OUT_PATH.stat().st_size / 1024
print(f"Exported {len(out)} contracts -> {OUT_PATH}  ({size_kb:.0f} KB)")
