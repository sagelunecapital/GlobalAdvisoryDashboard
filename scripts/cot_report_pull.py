# -*- coding: utf-8 -*-
"""
CFTC Legacy Futures-Only COT Report
Data Source : https://publicreporting.cftc.gov
Dataset ID  : 6dca-aqww  (Legacy Futures Only)

Note: NonComm/Comm columns only exist in the Legacy report.
      Disaggregated report (72hh-3qpy) uses Prod/Swap/ManagedMoney breakdown instead.

Output: data/cftc_cot.db  →  table: cot_legacy_futures
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from sodapy import Socrata

# ── Config ────────────────────────────────────────────────────────────────────
DATASET_ID = "6dca-aqww"
WEEKS_BACK = 500

DB_PATH    = Path(__file__).parent.parent / "data" / "cftc_cot.db"
TABLE_NAME = "cot_legacy_futures"

CONTRACT_CODES = [
    "191693", "232741", "133741", "096742", "090741", "073732",
    "083731", "085692", "002602", "033661", "12460+", "13874A",
    "099741", "111659", "088691", "097741", "054642", "189691",
    "057642", "133742", "209742", "023651", "075651", "076651",
    "239742", "084691", "005602", "080732", "092741", "098662",
    "043602", "042601", "044601", "020601", "001602", "067651",
]

API_COLUMNS = [
    "market_and_exchange_names",
    "yyyy_report_week_ww",
    "report_date_as_yyyy_mm_dd",
    "contract_market_name",
    "commodity_name",
    "cftc_contract_market_code",
    "open_interest_all",
    "noncomm_positions_long_all",
    "noncomm_positions_short_all",
    "comm_positions_long_all",
    "comm_positions_short_all",
]

NUMERIC_COLS = [
    "open_interest_all",
    "noncomm_positions_long_all",
    "noncomm_positions_short_all",
    "comm_positions_long_all",
    "comm_positions_short_all",
]

# ── Build SoQL query ──────────────────────────────────────────────────────────
cutoff    = (datetime.today() - timedelta(weeks=WEEKS_BACK)).strftime("%Y-%m-%dT00:00:00")
codes_sql = ", ".join(f"'{c}'" for c in CONTRACT_CODES)
where     = (
    f"cftc_contract_market_code in ({codes_sql})"
    f" AND report_date_as_yyyy_mm_dd >= '{cutoff}'"
)

# ── Fetch ─────────────────────────────────────────────────────────────────────
client = Socrata("publicreporting.cftc.gov", None)

print(f"Fetching last {WEEKS_BACK} weeks for {len(CONTRACT_CODES)} contracts …")
records = client.get_all(
    DATASET_ID,
    where=where,
    select=", ".join(API_COLUMNS),
    order="report_date_as_yyyy_mm_dd ASC",
)
df = pd.DataFrame.from_records(records)
print(f"  -> {len(df):,} rows | {df['cftc_contract_market_code'].nunique()} contracts found")

# ── Clean ─────────────────────────────────────────────────────────────────────
df["report_date"] = pd.to_datetime(df["report_date_as_yyyy_mm_dd"])
df.drop(columns=["report_date_as_yyyy_mm_dd"], inplace=True)
df[NUMERIC_COLS] = df[NUMERIC_COLS].apply(pd.to_numeric, errors="coerce")
df.sort_values(["cftc_contract_market_code", "report_date"], inplace=True)
df.reset_index(drop=True, inplace=True)

# ── Save to SQLite ────────────────────────────────────────────────────────────
print(f"Writing to {DB_PATH} …")
conn = sqlite3.connect(DB_PATH)
df.to_sql(TABLE_NAME, conn, if_exists="replace", index=False)

conn.execute(
    f"CREATE INDEX IF NOT EXISTS idx_code_date "
    f"ON {TABLE_NAME} (cftc_contract_market_code, report_date)"
)
conn.commit()

row_count = conn.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}").fetchone()[0]
conn.close()

print(f"  -> Saved {row_count:,} rows to table '{TABLE_NAME}'")
print("Done.")
