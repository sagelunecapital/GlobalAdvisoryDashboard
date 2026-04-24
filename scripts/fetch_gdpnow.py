#!/usr/bin/env python3
"""
Fetch Atlanta Fed GDPNow subcomponent contributions and write prototypes/gdpnow.json.

Columns in the Contributions sheet (row 2 = headers):
  A: Date  B: Forecast Quarter  C: PCE  D: BFI  E: Resid  F: Invent  G: Net Exp  H: Govt
  I: Change in GDP forecast  J: GDP forecast  K: Previous GDP forecast  L: Data Releases
"""

import io
import json
import os
import sys
from datetime import datetime, timezone

import openpyxl
import requests

XLSX_URL = (
    "https://www.atlantafed.org/-/media/Project/Atlanta/FRBA/Documents/"
    "cqer/researchcq/gdpnow/GDPTrackingModelDataAndForecasts.xlsx"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.atlantafed.org/research-and-data/data/gdpnow",
    "Accept": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*"
    ),
}

COMPONENT_MAP = {
    2: "Consumer Spending",          # PCE
    3: "Nonresidential Investments", # BFI
    4: "Residential Investments",    # Resid
    5: "Inventories",                # Invent
    6: "Net Exports",                # Net Exp
    7: "Government",                 # Govt
}
GDP_COL = 9   # column J (0-indexed) = GDP forecast

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_PATH = os.path.join(SCRIPT_DIR, "..", "prototypes", "gdpnow.json")


def safe_float(v):
    try:
        return round(float(v), 4)
    except (TypeError, ValueError):
        return None


def quarter_label(dt):
    q = (dt.month - 1) // 3 + 1
    return f"Q{q} {dt.year}"


def fetch_xlsx():
    print(f"Fetching {XLSX_URL} ...", flush=True)
    r = requests.get(XLSX_URL, headers=HEADERS, timeout=60)
    r.raise_for_status()
    print(f"  Downloaded {len(r.content):,} bytes", flush=True)
    return r.content


def parse(content):
    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    ws = wb["Contributions"]

    rows = []
    for row in ws.iter_rows(min_row=3, values_only=True):
        date_val, qtr_val = row[0], row[1]
        if not isinstance(date_val, datetime) or not isinstance(qtr_val, datetime):
            continue
        gdp = safe_float(row[GDP_COL])
        if gdp is None:
            continue
        comps = {label: safe_float(row[col]) for col, label in COMPONENT_MAP.items()}
        if any(v is None for v in comps.values()):
            continue
        rows.append({"date": date_val, "qtr": qtr_val, "gdp": gdp, "comps": comps})

    if not rows:
        raise ValueError("No valid rows parsed from Contributions sheet")

    # Group by forecast quarter, sort dates within each group
    quarters = {}
    for r in rows:
        key = r["qtr"]
        quarters.setdefault(key, []).append(r)

    result = {}
    for qtr_dt, qrows in sorted(quarters.items()):
        qrows.sort(key=lambda r: r["date"])
        label = quarter_label(qtr_dt)
        result[label] = {
            "dates": [r["date"].strftime("%Y-%m-%d") for r in qrows],
            "gdp":   [r["gdp"] for r in qrows],
            "components": {
                comp: [r["comps"][comp] for r in qrows]
                for comp in COMPONENT_MAP.values()
            },
        }

    return result


def main():
    content = fetch_xlsx()
    data = parse(content)

    quarters_sorted = sorted(
        data.keys(),
        key=lambda q: (int(q.split()[1]), int(q[1]))
    )
    latest = quarters_sorted[-1]

    print(f"  Quarters found: {len(data)}", flush=True)
    print(f"  Latest quarter: {latest}  ({len(data[latest]['dates'])} daily obs)", flush=True)
    print(f"  Latest date: {data[latest]['dates'][-1]}", flush=True)
    print(f"  Latest GDP estimate: {data[latest]['gdp'][-1]}%", flush=True)

    output = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "latest_quarter": latest,
        "quarters": data,
    }

    out_path = os.path.abspath(OUTPUT_PATH)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, separators=(",", ":"))
    print(f"  Written: {out_path}", flush=True)

    # Clean up test file if present
    test_file = os.path.join(os.path.dirname(out_path), "gdpnow_test.xlsx")
    if os.path.exists(test_file):
        os.remove(test_file)


if __name__ == "__main__":
    main()
