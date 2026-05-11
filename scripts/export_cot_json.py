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
    "067651": "Crude Oil",
    "111659": "Gasoline",
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
    "001602": "Wheat",
    "073732": "Cocoa",
    "083731": "Coffee",
    "033661": "Cotton",
    "054642": "Lean Hogs",
    "057642": "Live Cattle",
    "080732": "Sugar",
    "099741": "Euro FX",
    "096742": "British Pound",
    "097741": "Japanese Yen",
    "090741": "Canadian Dollar",
    "232741": "Australian Dollar",
    "092741": "Swiss Franc",
    "098662": "US Dollar Index",
    "020601": "30Y Bonds",
    "043602": "10Y Notes",
    "044601": "5Y Notes",
    "042601": "2Y Notes",
    "13874A": "S&P 500",
    "209742": "Nasdaq",
    "239742": "Russell 2000",
    "12460+": "Dow Jones",
    "133742": "Bitcoin",
}

CLASS_MAP = {
    "Energy":      ["067651", "111659", "023651"],
    "Metals":      ["088691", "084691", "085692", "075651", "076651", "191693", "189691"],
    "Agriculture": ["002602", "005602", "001602", "073732", "083731", "033661", "080732", "054642", "057642"],
    "Currencies":  ["099741", "096742", "097741", "090741", "232741", "092741", "098662"],
    "Bonds":       ["020601", "043602", "044601", "042601"],
    "Indices":     ["13874A", "209742", "239742", "12460+", "133742"],
}

CURRENCY_INDEX_COMPONENTS = ["099741", "096742", "097741", "090741", "232741", "092741"]
EQUITIES_INDEX_COMPONENTS  = ["13874A", "209742", "239742", "12460+"]

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
            "dates": [r["report_date"] for r in rows],
            "oi":    [r2i(r["oi"]) for r in rows],
            "cl":    [r2i(r["cl"]) for r in rows],
            "cs":    [r2i(r["cs"]) for r in rows],
            "nl":    [r2i(r["nl"]) for r in rows],
            "ns":    [r2i(r["ns"]) for r in rows],
        }

conn.close()


def _build_composite(key, display_name, cls, component_codes, data_dict):
    """Sum net-position columns across component contracts, intersecting on report_date."""
    parts = [data_dict[c] for c in component_codes if c in data_dict]
    if not parts:
        return
    # Build week→index maps for each component
    week_idx = [{w: i for i, w in enumerate(p["weeks"])} for p in parts]
    common_weeks = sorted(
        set(week_idx[0]).intersection(*(m.keys() for m in week_idx[1:]))
    )
    if not common_weeks:
        return

    # Dates from the first component (same date for a given week across components)
    first_date_map = {w: parts[0]["dates"][i] for i, w in enumerate(parts[0]["weeks"])}

    def _sum_col(col):
        result = []
        for w in common_weeks:
            total = 0
            for p, idx_map in zip(parts, week_idx):
                v = p[col][idx_map[w]]
                total += v if v is not None else 0
            result.append(round(total))
        return result

    data_dict[key] = {
        "name":  display_name,
        "class": cls,
        "weeks": common_weeks,
        "dates": [first_date_map.get(w, "") for w in common_weeks],
        "oi":    _sum_col("oi"),
        "cl":    _sum_col("cl"),
        "cs":    _sum_col("cs"),
        "nl":    _sum_col("nl"),
        "ns":    _sum_col("ns"),
    }


_build_composite("CURRENCY_INDEX", "Currency Index", "Currencies", CURRENCY_INDEX_COMPONENTS, out)
_build_composite("EQUITIES_INDEX", "Equities Index", "Indices",    EQUITIES_INDEX_COMPONENTS,  out)

with open(OUT_PATH, "w", encoding="utf-8") as f:
    json.dump(out, f, separators=(",", ":"))

size_kb = OUT_PATH.stat().st_size / 1024
print(f"Exported {len(out)} contracts -> {OUT_PATH}  ({size_kb:.0f} KB)")
