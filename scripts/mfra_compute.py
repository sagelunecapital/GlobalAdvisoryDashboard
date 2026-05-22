#!/usr/bin/env python3
"""
mfra_compute.py  —  Multi-Factor Return Attribution
Orthogonalized 3-factor rolling OLS replicating the Pine Script MFRA indicator.

Factor hierarchy (mirrors Pine Script logic):
  f_mkt = SPX return
  f_sec = sector_return  - SPX_return
  f_sub = subsector_return - sector_return

Sector / subsector mapping (per user spec):
  Ticker WITHOUT sub_industry:
    sector     = equal-wtd avg of all leaf groups in same (country, sector)
    subsector  = leaf group for (country, industry)

  Ticker WITH sub_industry:
    sector     = equal-wtd avg of all leaf groups in same (country, industry)
    subsector  = leaf group for (country, industry: sub_industry)

Output table  mfra_daily  (yf_ticker, date):
  alpha, beta_mkt, beta_sec, beta_sub,
  mkt_contrib, sec_contrib, sub_contrib, resid_contrib,  [percentage points]
  r_squared
"""

import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

DB_F       = Path(__file__).resolve().parent.parent / "Sector Rotation" / "sector_rotation.db"
SPX_TICKER = "^GSPC"
OLS_WINDOW = 21


# ── helpers ──────────────────────────────────────────────────────────────────

def leaf_group_id(country: str, industry: str, sub_industry: str) -> str:
    name = f"{country} {industry}"
    if sub_industry and sub_industry.strip():
        name += f": {sub_industry.strip()}"
    return name


def init_table(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS mfra_daily (
            yf_ticker     TEXT,
            date          TEXT,
            alpha         REAL,
            beta_mkt      REAL,
            beta_sec      REAL,
            beta_sub      REAL,
            mkt_contrib   REAL,
            sec_contrib   REAL,
            sub_contrib   REAL,
            resid_contrib REAL,
            r_squared     REAL,
            PRIMARY KEY (yf_ticker, date)
        );
        CREATE INDEX IF NOT EXISTS idx_mfra_ticker_date
            ON mfra_daily (yf_ticker, date);
    """)
    conn.commit()


def rolling_ols(stock_ret: np.ndarray,
                f_mkt: np.ndarray,
                f_sec: np.ndarray,
                f_sub: np.ndarray,
                window: int = OLS_WINDOW):
    """
    For each bar t in [window, len), fit OLS on the window [t-window, t)
    and record contributions AT bar t.

    Returns list of tuples:
      (alpha, beta_mkt, beta_sec, beta_sub,
       mkt_contrib, sec_contrib, sub_contrib, resid_contrib, r_squared)
    One tuple per bar starting at index `window`.
    """
    n = len(stock_ret)
    nan_row = (np.nan,) * 9
    out = []

    for t in range(window, n):
        y  = stock_ret[t - window : t]
        x1 = f_mkt[t - window : t]
        x2 = f_sec[t - window : t]
        x3 = f_sub[t - window : t]

        X = np.column_stack([np.ones(window), x1, x2, x3])

        # Skip windows with NaN or degenerate columns
        if np.isnan(y).any() or np.isnan(X).any():
            out.append(nan_row)
            continue
        if np.all(x1 == 0) and np.all(x2 == 0) and np.all(x3 == 0):
            out.append(nan_row)
            continue

        try:
            beta, _, rank, _ = np.linalg.lstsq(X, y, rcond=None)
        except np.linalg.LinAlgError:
            out.append(nan_row)
            continue

        if rank < 4:
            out.append(nan_row)
            continue

        alpha, b_mkt, b_sec, b_sub = beta

        y_hat  = X @ beta
        ss_res = float(np.sum((y - y_hat) ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r2     = (1.0 - ss_res / ss_tot) if ss_tot > 1e-20 else np.nan

        # Contributions at bar t (current-day factors, percentage points)
        mc = b_mkt * f_mkt[t] * 100.0
        sc = b_sec * f_sec[t] * 100.0
        uc = b_sub * f_sub[t] * 100.0
        rc = stock_ret[t] * 100.0 - mc - sc - uc

        out.append((alpha, b_mkt, b_sec, b_sub, mc, sc, uc, rc, r2))

    return out


# ── main ─────────────────────────────────────────────────────────────────────

def main(full: bool = False) -> None:
    t0 = time.time()
    conn = sqlite3.connect(DB_F)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    init_table(conn)

    # ── Incremental cutoff ───────────────────────────────────────────────────
    last_date_str = None
    if not full:
        row = conn.execute("SELECT MAX(date) FROM mfra_daily").fetchone()
        last_date_str = row[0] if row and row[0] else None

    print("[1] Loading price & group data...")

    # Stock prices (all tickers)
    raw = pd.read_sql("SELECT yf_ticker, date, close FROM daily ORDER BY date", conn)
    raw["date"] = pd.to_datetime(raw["date"])

    # SPX price
    spx_series = (raw[raw["yf_ticker"] == SPX_TICKER]
                  .set_index("date")["close"]
                  .sort_index())
    if spx_series.empty:
        raise RuntimeError("SPX (^GSPC) not found in daily table.")

    # Group index levels → returns
    gr = pd.read_sql("SELECT group_id, date, index_level FROM group_rs ORDER BY date", conn)
    gr["date"] = pd.to_datetime(gr["date"])
    group_wide = gr.pivot(index="date", columns="group_id", values="index_level")
    group_ret  = group_wide.pct_change()          # NaN on first row per group

    # Industry classification
    ind = pd.read_sql(
        "SELECT yf_ticker, country, sector, industry, sub_industry FROM industry", conn
    )
    ind["sub_industry"] = ind["sub_industry"].fillna("")

    ind["leaf_gid"] = ind.apply(
        lambda r: leaf_group_id(r["country"], r["industry"], r["sub_industry"]), axis=1
    )

    # Master trading calendar = SPX dates (avoids including non-US holidays in rolling window)
    calendar = spx_series.index.sort_values()

    # ── Trim calendar for incremental run ────────────────────────────────────
    if last_date_str:
        last_dt = pd.Timestamp(last_date_str)
        after_pos = int(calendar.searchsorted(last_dt, side="right"))
        if after_pos >= len(calendar):
            print(f"Already up to date (last: {last_date_str}). Nothing to compute.")
            conn.close()
            return
        new_count = len(calendar) - after_pos
        start_pos = max(0, after_pos - OLS_WINDOW)
        calendar = calendar[start_pos:]
        raw = raw[raw["date"] >= calendar[0]]
        print(f"[incremental] +{new_count} new date(s) since {last_date_str}. "
              f"Window: {calendar[0].date()} to {calendar[-1].date()}")
    else:
        print("[full] No existing data — running full history.")

    spx_ret = spx_series.pct_change().reindex(calendar).fillna(0.0)

    # Align group_ret to calendar (forward-fill gaps for intl markets, then 0)
    group_ret_cal = group_ret.reindex(calendar).ffill().fillna(0.0)

    # ── Build synthetic sector / industry return caches ──────────────────────
    print("[2] Building synthetic sector / industry indices...")

    # Map (country, sector) → leaf group_ids present in group_ret_cal
    cs_groups: dict[tuple, list] = {}
    ci_groups: dict[tuple, list] = {}
    for _, row in ind.iterrows():
        gid = row["leaf_gid"]
        if gid not in group_ret_cal.columns:
            continue
        cs_key = (row["country"], row["sector"])
        ci_key = (row["country"], row["industry"])
        cs_groups.setdefault(cs_key, []).append(gid)
        ci_groups.setdefault(ci_key, []).append(gid)

    # Deduplicate
    cs_groups = {k: list(set(v)) for k, v in cs_groups.items()}
    ci_groups = {k: list(set(v)) for k, v in ci_groups.items()}

    # Precompute equal-weighted average returns for each unique group set
    cs_ret: dict[tuple, np.ndarray] = {}
    ci_ret: dict[tuple, np.ndarray] = {}

    for key, gids in cs_groups.items():
        cs_ret[key] = group_ret_cal[gids].mean(axis=1).values

    for key, gids in ci_groups.items():
        ci_ret[key] = group_ret_cal[gids].mean(axis=1).values

    zeros = np.zeros(len(calendar))

    # ── Per-ticker rolling OLS ────────────────────────────────────────────────
    print(f"[3] Running rolling OLS (window={OLS_WINDOW}d) for {len(ind)} tickers...")

    spx_arr = spx_ret.values
    rows_out: list[tuple] = []
    dates_arr = np.array([d.date() for d in calendar])

    for idx, row in ind.iterrows():
        yf_t       = row["yf_ticker"]
        country    = row["country"]
        sector     = row["sector"]
        industry   = row["industry"]
        sub_ind    = row["sub_industry"]
        leaf       = row["leaf_gid"]
        has_sub    = bool(sub_ind and sub_ind.strip())

        # Stock returns aligned to calendar
        stk_prices = (raw[raw["yf_ticker"] == yf_t]
                      .set_index("date")["close"]
                      .reindex(calendar)
                      .ffill())
        stk_ret = stk_prices.pct_change().fillna(0.0).values

        # Skip tickers that are almost entirely missing
        if np.isnan(stk_prices.values).mean() > 0.6:
            continue

        # Sector and sub-sector return arrays
        if has_sub:
            sec_arr = ci_ret.get((country, industry), zeros)
            sub_arr = (group_ret_cal[leaf].values
                       if leaf in group_ret_cal.columns else sec_arr)
        else:
            sec_arr = cs_ret.get((country, sector), zeros)
            sub_arr = (group_ret_cal[leaf].values
                       if leaf in group_ret_cal.columns else sec_arr)

        # Orthogonalize
        f_mkt = spx_arr
        f_sec = sec_arr - spx_arr
        f_sub = sub_arr - sec_arr

        # Rolling OLS
        results = rolling_ols(stk_ret, f_mkt, f_sec, f_sub, OLS_WINDOW)

        date_subset = dates_arr[OLS_WINDOW:]
        for j, vals in enumerate(results):
            alpha, b_mkt, b_sec, b_sub, mc, sc, uc, rc, r2 = vals
            rows_out.append((
                yf_t,
                str(date_subset[j]),
                _f(alpha), _f(b_mkt), _f(b_sec), _f(b_sub),
                _f(mc), _f(sc), _f(uc), _f(rc), _f(r2),
            ))

        if (idx + 1) % 200 == 0:
            print(f"  {idx + 1}/{len(ind)}  ({len(rows_out):,} rows)  "
                  f"{time.time()-t0:.0f}s")

    print(f"[4] Writing {len(rows_out):,} rows to mfra_daily...")
    if full or not last_date_str:
        conn.execute("DELETE FROM mfra_daily")
    conn.executemany("""
        INSERT OR REPLACE INTO mfra_daily
          (yf_ticker, date, alpha, beta_mkt, beta_sec, beta_sub,
           mkt_contrib, sec_contrib, sub_contrib, resid_contrib, r_squared)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, rows_out)
    conn.commit()
    conn.close()

    elapsed = time.time() - t0
    print(f"Done in {elapsed:.0f}s.  {len(rows_out):,} rows written.")


def _f(v):
    return None if (v is None or (isinstance(v, float) and np.isnan(v))) else round(float(v), 6)


if __name__ == "__main__":
    main(full="--full" in sys.argv)
