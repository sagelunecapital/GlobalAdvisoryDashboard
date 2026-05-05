#!/usr/bin/env python3
"""
Sector Rotation Data Collector
Uses SQLite so only new rows are written each day — no full-dataset reload.

Database: Sector Rotation/sector_rotation.db
  table  industry     — ticker classification (static)
  table  daily        — (yf_ticker, date) PK; Close, Volume, EMA_20, EMA_200
  table  market_caps  — (yf_ticker, date) monthly market cap snapshots
  table  group_rs      — (group_id, date) index level, RS, EMA_21_RS, signal
  table  group_summary — (group_id, date) RS rankings within country, performance metrics

Moving averages: Exponential (EMA), adjust=False
  EMA_t = close * k + EMA_{t-1} * (1 - k),  k = 2 / (span + 1)

Group indices: market-cap weighted, rebalanced monthly.
  Index and SPX both normalised to 100 at the earliest common date.
  RS = group_index / spx_index  (>1.0 = outperforming SPX)
  Signal = RS - EMA_21_RS  (only populated when RS > EMA_21_RS)
"""

import sqlite3
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# ── Config ─────────────────────────────────────────────────────────────────
BASE_DIR     = Path(r"P:\OneDrive\[03] Cowork\Sector Rotation")
INDUSTRY_F   = BASE_DIR / "Industry Classification Data.csv"
DB_F         = BASE_DIR / "sector_rotation.db"
EXCEL_F      = BASE_DIR / "Sector_Rotation_Data.xlsx"
LOG_F        = BASE_DIR / "data_collector.log"

HISTORY_DAYS = 1000  # days on first run — needs 800+ for 200D EMA to converge
BATCH_SIZE   = 150   # tickers per yfinance download call
SPX_TICKER   = "^GSPC"


# ── Ticker mapping ─────────────────────────────────────────────────────────
def to_yf_ticker(ticker: str, country: str) -> str:
    raw = str(ticker).strip()
    if country == "United States":
        return raw.replace("/", "-")
    if country == "China":
        code = raw.split()[0]
        if not code.isdigit():
            return raw
        n = len(code)
        if n <= 5:
            return f"{int(code):04d}.HK"
        return f"{code}.SS" if code[0] in ("6", "9") else f"{code}.SZ"
    if country == "Korea":
        code = raw.split()[0]
        if code.isdigit():
            return f"{int(code):06d}.KS"
    return raw


# ── Database ───────────────────────────────────────────────────────────────
def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_F)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS industry (
            ticker       TEXT,
            yf_ticker    TEXT PRIMARY KEY,
            country      TEXT,
            sector       TEXT,
            industry     TEXT,
            sub_industry TEXT
        );

        CREATE TABLE IF NOT EXISTS daily (
            yf_ticker TEXT,
            ticker    TEXT,
            date      TEXT,
            close     REAL,
            volume    INTEGER,
            ema_20    REAL,
            ema_200   REAL,
            PRIMARY KEY (yf_ticker, date)
        );

        CREATE INDEX IF NOT EXISTS idx_daily_ticker_date
            ON daily (yf_ticker, date);

        CREATE TABLE IF NOT EXISTS market_caps (
            yf_ticker  TEXT,
            date       TEXT,
            market_cap REAL,
            PRIMARY KEY (yf_ticker, date)
        );

        CREATE TABLE IF NOT EXISTS group_rs (
            group_id     TEXT,
            date         TEXT,
            index_level  REAL,
            rs           REAL,
            ema_21_rs    REAL,
            rs_minus_ema REAL,
            PRIMARY KEY (group_id, date)
        );

        CREATE TABLE IF NOT EXISTS group_summary (
            group_id        TEXT,
            date            TEXT,
            rs_rank_daily   REAL,
            rs_rank_weekly  REAL,
            rs_rank_monthly REAL,
            perf_1d         REAL,
            perf_5d         REAL,
            perf_10d        REAL,
            perf_1m         REAL,
            perf_2m         REAL,
            perf_3m         REAL,
            PRIMARY KEY (group_id, date)
        );
    """)
    conn.commit()


def migrate_schema_to_ema(conn: sqlite3.Connection) -> None:
    """One-time: rename ma_20/ma_200 -> ema_20/ema_200 and recalculate."""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(daily)").fetchall()]
    if "ema_20" in cols:
        return

    print("  [migration] Renaming SMA columns to EMA and recalculating...")
    conn.executescript("""
        ALTER TABLE daily RENAME TO daily_old;
        CREATE TABLE daily (
            yf_ticker TEXT, ticker TEXT, date TEXT,
            close REAL, volume INTEGER, ema_20 REAL, ema_200 REAL,
            PRIMARY KEY (yf_ticker, date)
        );
        INSERT INTO daily (yf_ticker, ticker, date, close, volume)
            SELECT yf_ticker, ticker, date, close, volume FROM daily_old;
        DROP TABLE daily_old;
        CREATE INDEX IF NOT EXISTS idx_daily_ticker_date ON daily (yf_ticker, date);
    """)
    conn.commit()

    df = pd.read_sql(
        "SELECT yf_ticker, date, close FROM daily ORDER BY yf_ticker, date", conn
    )
    df["ema_20"]  = df.groupby("yf_ticker")["close"].transform(
        lambda x: x.ewm(span=20,  adjust=False).mean().round(4)
    )
    df["ema_200"] = df.groupby("yf_ticker")["close"].transform(
        lambda x: x.ewm(span=200, adjust=False).mean().round(4)
    )
    conn.executemany(
        "UPDATE daily SET ema_20=?, ema_200=? WHERE yf_ticker=? AND date=?",
        df[["ema_20", "ema_200", "yf_ticker", "date"]].itertuples(index=False, name=None),
    )
    conn.commit()
    print(f"  [migration] Done — {len(df):,} rows updated.")


def upsert_industry(conn: sqlite3.Connection, df: pd.DataFrame) -> None:
    conn.executemany(
        """INSERT OR REPLACE INTO industry
           (ticker, yf_ticker, country, sector, industry, sub_industry)
           VALUES (?,?,?,?,?,?)""",
        df[["Ticker", "YF_Ticker", "Country", "Sector", "Industry", "Sub-Industry"]]
          .fillna("").itertuples(index=False, name=None),
    )
    conn.commit()


def get_last_date(conn: sqlite3.Connection) -> date | None:
    # Use the earliest per-ticker max among recently-active tickers (last_date
    # within 7 days of the global max). This fills gaps from markets with
    # different calendars (HK vs US) without being dragged back by delisted
    # tickers that permanently stopped updating.
    row = conn.execute("SELECT MAX(date) FROM daily").fetchone()
    if not row[0]:
        return None
    global_max = datetime.strptime(row[0], "%Y-%m-%d").date()
    cutoff = (global_max - timedelta(days=7)).strftime("%Y-%m-%d")
    row2 = conn.execute(
        "SELECT MIN(last_date) FROM "
        "(SELECT MAX(date) AS last_date FROM daily GROUP BY yf_ticker "
        " HAVING MAX(date) >= ?)",
        (cutoff,),
    ).fetchone()
    return datetime.strptime(row2[0], "%Y-%m-%d").date() if row2[0] else global_max


def db_row_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM daily").fetchone()[0]


# ── Industry data ──────────────────────────────────────────────────────────
def load_industry() -> pd.DataFrame:
    df = pd.read_csv(INDUSTRY_F, dtype=str).fillna("")
    df.columns = [c.strip() for c in df.columns]
    if "Sub-Industry" not in df.columns:
        df["Sub-Industry"] = ""
    df["YF_Ticker"] = df.apply(
        lambda r: to_yf_ticker(r["Ticker"], r["Country"]), axis=1
    )
    return df


# ── yfinance price fetch ───────────────────────────────────────────────────
def fetch(yf_tickers: list, start: str, end: str) -> pd.DataFrame:
    rows  = []
    total = (len(yf_tickers) - 1) // BATCH_SIZE + 1

    for i in range(0, len(yf_tickers), BATCH_SIZE):
        batch = yf_tickers[i : i + BATCH_SIZE]
        n     = i // BATCH_SIZE + 1
        print(f"  Batch {n}/{total}  ({len(batch)} tickers)...")
        raw = None
        for attempt in range(3):
            try:
                raw = yf.download(
                    batch, start=start, end=end,
                    auto_adjust=True, progress=False,
                    threads=True, group_by="ticker",
                )
                break
            except Exception as e:
                if attempt < 2:
                    import time
                    wait = 15 * (attempt + 1)
                    print(f"  [retry] Batch {n} attempt {attempt+1} failed ({e}). Waiting {wait}s...")
                    time.sleep(wait)
                else:
                    print(f"  [error] Batch {n} failed after 3 attempts: {e}")
        if raw is None:
            continue

        if raw is None or raw.empty:
            continue

        if len(batch) == 1 and not isinstance(raw.columns, pd.MultiIndex):
            # Older yfinance returns flat columns for a single ticker — wrap them
            t = batch[0]
            if "Close" not in raw.columns:
                continue
            tmp = raw[["Close", "Volume"]].copy()
            tmp.columns = pd.MultiIndex.from_tuples([(t, "Close"), (t, "Volume")])
            raw = tmp
        # Multi-ticker downloads (and newer yfinance single-ticker) already
        # return (ticker, metric) MultiIndex — no conversion needed

        for t in batch:
            try:
                close  = raw[t]["Close"].dropna()
                volume = raw[t]["Volume"].reindex(close.index).fillna(0)
            except (KeyError, TypeError):
                continue
            for dt, c in close.items():
                rows.append({
                    "YF_Ticker": t,
                    "Date":      pd.Timestamp(dt).date(),
                    "Close":     round(float(c), 4),
                    "Volume":    int(volume.get(dt, 0)),
                })

    return pd.DataFrame(rows)


# ── EMA insert (only needs previous EMA per ticker — 1 row each) ───────────
K20  = 2 / 21
K200 = 2 / 201


def compute_and_insert(conn: sqlite3.Connection,
                       new_raw: pd.DataFrame,
                       ticker_lookup: pd.DataFrame) -> int:
    new_raw  = new_raw.merge(ticker_lookup, on="YF_Ticker", how="left")
    tickers  = new_raw["YF_Ticker"].unique().tolist()
    ph       = ",".join("?" * len(tickers))

    prev_df  = pd.read_sql_query(
        f"""SELECT yf_ticker, ema_20, ema_200 FROM (
                SELECT yf_ticker, ema_20, ema_200,
                       ROW_NUMBER() OVER (PARTITION BY yf_ticker ORDER BY date DESC) AS rn
                FROM daily WHERE yf_ticker IN ({ph})
            ) WHERE rn = 1""",
        conn, params=tickers,
    )
    prev = prev_df.set_index("yf_ticker")[["ema_20", "ema_200"]].to_dict("index")

    rows = []
    for yf_ticker, grp in new_raw.groupby("YF_Ticker"):
        grp  = grp.sort_values("Date")
        seed = prev.get(yf_ticker, {})
        e20  = seed.get("ema_20")
        e200 = seed.get("ema_200")

        for _, row in grp.iterrows():
            c    = float(row["Close"])
            e20  = c if e20  is None else round(c * K20  + e20  * (1 - K20),  4)
            e200 = c if e200 is None else round(c * K200 + e200 * (1 - K200), 4)
            rows.append((
                yf_ticker, row.get("Ticker", ""), str(row["Date"]),
                round(c, 4), int(row["Volume"]), e20, e200,
            ))

    conn.executemany(
        "INSERT OR IGNORE INTO daily (yf_ticker,ticker,date,close,volume,ema_20,ema_200) VALUES (?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    return len(rows)


# ── Market cap fetch (monthly) ─────────────────────────────────────────────
def needs_cap_refresh(conn: sqlite3.Connection, today: date) -> bool:
    row = conn.execute("SELECT MAX(date) FROM market_caps").fetchone()
    if not row[0]:
        return True
    last = datetime.strptime(row[0], "%Y-%m-%d").date()
    return last.year != today.year or last.month != today.month


def _fetch_one_cap(ticker: str):
    try:
        mc = yf.Ticker(ticker).fast_info.market_cap
        return ticker, float(mc) if (mc and mc > 0) else None
    except Exception:
        return ticker, None


def fetch_and_store_market_caps(
    conn: sqlite3.Connection, tickers: list, ref_date: str
) -> None:
    print(f"  Fetching market caps for {len(tickers)} tickers (monthly refresh)...")
    rows, done = [], 0
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(_fetch_one_cap, t): t for t in tickers}
        for f in as_completed(futs):
            ticker, mc = f.result()
            done += 1
            if mc:
                rows.append((ticker, ref_date, mc))
            if done % 300 == 0:
                print(f"    {done}/{len(tickers)}...")
    conn.executemany(
        "INSERT OR REPLACE INTO market_caps (yf_ticker, date, market_cap) VALUES (?,?,?)",
        rows,
    )
    conn.commit()
    print(f"  Stored {len(rows)}/{len(tickers)} market caps for {ref_date}.")


# ── Group RS computation (full recompute, runs after each daily fetch) ─────
def group_display_name(country: str, industry: str, sub_industry: str) -> str:
    name = f"{country} {industry}"
    if sub_industry and sub_industry.strip():
        name += f": {sub_industry.strip()}"
    return name


def compute_group_rs(conn: sqlite3.Connection, industry_df: pd.DataFrame) -> None:
    """
    Compute market-cap weighted group performance indices, RS vs SPX,
    21D EMA of RS, and the RS - EMA signal (populated only when RS > EMA).

    Both the group index and SPX are normalised to 100 at the earliest
    common date so RS ~ 1.0 = equal performance, > 1.0 = outperforming.
    Weights rebalance on the first trading day of each calendar month.
    Full recompute on every call (EMA of RS requires full history).
    """
    print("  Loading price history for RS computation...")

    raw = pd.read_sql("SELECT yf_ticker, date, close FROM daily ORDER BY date", conn)
    raw["date"] = pd.to_datetime(raw["date"]).dt.date

    # SPX series
    spx_raw = raw[raw["yf_ticker"] == SPX_TICKER].set_index("date")["close"]
    if spx_raw.empty:
        print("  [warn] SPX data not found — skipping RS computation.")
        return

    # Wide price table (all tickers except SPX)
    price_wide = (
        raw[raw["yf_ticker"] != SPX_TICKER]
        .pivot(index="date", columns="yf_ticker", values="close")
    )

    # Align SPX to trading dates
    spx_aligned = spx_raw.reindex(price_wide.index).ffill()

    # Normalise SPX to 100 at first date
    spx_perf = spx_aligned / spx_aligned.iloc[0] * 100

    # Daily returns for all tickers
    daily_ret = price_wide.pct_change()

    trading_dates = price_wide.index
    date_month    = pd.PeriodIndex(pd.DatetimeIndex(trading_dates), freq="M")

    # Market caps: pivot to (month Period) x ticker
    mc_raw = pd.read_sql("SELECT yf_ticker, date, market_cap FROM market_caps", conn)
    if not mc_raw.empty:
        mc_raw["month"] = pd.to_datetime(mc_raw["date"]).dt.to_period("M")
        mc_pivot = mc_raw.pivot_table(
            index="month", columns="yf_ticker", values="market_cap", aggfunc="last"
        )
        mc_months = sorted(mc_pivot.index)
    else:
        mc_pivot  = pd.DataFrame()
        mc_months = []

    # Group definitions
    industry_df = industry_df.copy()
    industry_df["group_id"] = industry_df.apply(
        lambda r: group_display_name(
            r["Country"], r.get("Industry", ""), r.get("Sub-Industry", "")
        ),
        axis=1,
    )

    unique_months = sorted(date_month.unique())
    all_rows = []
    n_groups = industry_df["group_id"].nunique()
    print(f"  Computing RS for {n_groups} groups...")

    for gid, members in industry_df.groupby("group_id"):
        tickers = [t for t in members["YF_Ticker"].tolist() if t in price_wide.columns]
        if not tickers:
            continue

        ret_g = daily_ret[tickers]

        # ── Pre-compute monthly weight vectors ──────────────────────────
        month_w: dict = {}
        for m in unique_months:
            if mc_months:
                # Most recent cap snapshot at or before this month
                prior = [mm for mm in mc_months if mm <= m]
                if prior:
                    caps = mc_pivot.loc[prior[-1]].reindex(tickers).fillna(0)
                else:
                    caps = pd.Series(0.0, index=tickers)
            else:
                caps = pd.Series(0.0, index=tickers)

            total = caps.sum()
            w = caps / total if total > 0 else pd.Series(1.0 / len(tickers), index=tickers)
            month_w[m] = w

        # ── Build full weight DataFrame aligned to trading dates ─────────
        weight_df = pd.DataFrame(
            [month_w[m].values for m in date_month],
            index=trading_dates,
            columns=tickers,
        )

        # ── Weighted returns -> performance index (base 100) ─────────────
        wr        = (ret_g.fillna(0) * weight_df).sum(axis=1)
        idx_level = (1 + wr).cumprod() * 100

        # ── RS = group index / SPX index (both base 100) ─────────────────
        rs  = (idx_level / spx_perf).dropna()
        if rs.empty:
            continue

        # ── 21D EMA of RS ────────────────────────────────────────────────
        ema21 = rs.ewm(span=21, adjust=False).mean()

        # ── Signal: RS - EMA only when RS > EMA ──────────────────────────
        signal = (rs - ema21).where(rs > ema21)

        for dt in rs.index:
            sig = signal.get(dt)
            all_rows.append((
                gid,
                str(dt),
                round(float(idx_level[dt]), 4),
                round(float(rs[dt]),        6),
                round(float(ema21[dt]),     6),
                round(float(sig), 6) if pd.notna(sig) else None,
            ))

    conn.execute("DELETE FROM group_rs")
    conn.executemany(
        """INSERT INTO group_rs
           (group_id, date, index_level, rs, ema_21_rs, rs_minus_ema)
           VALUES (?,?,?,?,?,?)""",
        all_rows,
    )
    conn.commit()
    computed = len({r[0] for r in all_rows})
    print(f"  Stored {len(all_rows):,} rows for {computed} groups.")


# ── Group summary: RS rankings + performance ──────────────────────────────
def compute_group_summary(conn: sqlite3.Connection, industry_df: pd.DataFrame) -> None:
    """
    Compute per-group RS rankings (within country) and performance metrics.

    RS rankings: PERCENTRANK within country × 100 for three time points:
      - daily:   rank of today's RS vs all same-country groups today
      - weekly:  rank of RS from 5 trading days ago
      - monthly: rank of RS from 21 trading days ago
    Formula: (rank_min - 1) / (n_valid - 1) * 100  (matches Excel PERCENTRANK)

    Performance: group index pct_change over 1, 5, 10, 21, 42, 63 trading days.
    """
    print("  Loading group RS data for summary computation...")

    rs_df = pd.read_sql(
        "SELECT group_id, date, index_level, rs FROM group_rs ORDER BY date", conn
    )
    if rs_df.empty:
        print("  [warn] No group RS data — skipping summary.")
        return

    rs_df["date"] = pd.to_datetime(rs_df["date"]).dt.date

    # Build country mapping
    idf = industry_df.copy()
    if "group_id" not in idf.columns:
        idf["group_id"] = idf.apply(
            lambda r: group_display_name(
                r["Country"], r.get("Industry", ""), r.get("Sub-Industry", "")
            ),
            axis=1,
        )
    country_map = idf.drop_duplicates("group_id").set_index("group_id")["Country"]

    # Wide format: trading dates × group_id
    idx_wide = rs_df.pivot(index="date", columns="group_id", values="index_level")
    rs_wide  = rs_df.pivot(index="date", columns="group_id", values="rs")

    # ── Performance metrics (pct change of index_level) ──────────────────────
    perf_frames: dict = {}
    for label, n in [
        ("perf_1d", 1), ("perf_5d", 5), ("perf_10d", 10),
        ("perf_1m", 21), ("perf_2m", 42), ("perf_3m", 63),
    ]:
        perf_frames[label] = (idx_wide.pct_change(n) * 100).round(4)

    # ── RS rankings within country ────────────────────────────────────────────
    def _percentrank_row(row: pd.Series) -> pd.Series:
        """Excel PERCENTRANK: (rank_min - 1) / (n - 1) * 100, per row."""
        n = int(row.notna().sum())
        if n == 0:
            return pd.Series(float("nan"), index=row.index)
        if n == 1:
            # Only one valid value — return 100 for it, NaN for nulls
            return row.where(row.isna(), 100.0)
        ranks = row.rank(method="min")
        return ((ranks - 1) / (n - 1) * 100).round(2)

    rank_frames: dict = {}
    for label, lag in [
        ("rs_rank_daily", 0), ("rs_rank_weekly", 5), ("rs_rank_monthly", 21),
    ]:
        rs_lagged = rs_wide.shift(lag) if lag > 0 else rs_wide
        ranked    = pd.DataFrame(
            float("nan"), index=rs_lagged.index, columns=rs_lagged.columns
        )
        for country in country_map.unique():
            gids       = country_map[country_map == country].index.tolist()
            valid_gids = [g for g in gids if g in rs_lagged.columns]
            if not valid_gids:
                continue
            ranked[valid_gids] = rs_lagged[valid_gids].apply(_percentrank_row, axis=1)

        rank_frames[label] = ranked

    # ── Combine into long format and write ────────────────────────────────────
    all_wide = {**rank_frames, **perf_frames}
    long_parts = []
    for col_name, wide_df in all_wide.items():
        melted = (
            wide_df.reset_index()
            .melt(id_vars="date", var_name="group_id", value_name=col_name)
        )
        long_parts.append(melted.set_index(["date", "group_id"]))

    combined = pd.concat(long_parts, axis=1).reset_index()
    combined["date"] = combined["date"].astype(str)

    # Drop rows where every metric is null (e.g., first few rows where lags exceed history)
    metric_cols = list(all_wide.keys())
    combined = combined.dropna(how="all", subset=metric_cols)

    conn.execute("DELETE FROM group_summary")
    # chunksize capped at floor(999 / num_columns) for SQLite's variable limit
    n_cols = len(combined.columns)
    chunk  = max(1, 999 // n_cols)
    combined.to_sql(
        "group_summary", conn, if_exists="append",
        index=False, method="multi", chunksize=chunk,
    )
    conn.commit()

    n_groups = combined["group_id"].nunique()
    print(f"  Stored {len(combined):,} summary rows for {n_groups} groups.")


# ── Excel migration (first-run fallback) ───────────────────────────────────
def migrate_from_excel(conn: sqlite3.Connection) -> bool:
    if not EXCEL_F.exists():
        return False
    print(f"  Found {EXCEL_F.name} — migrating to SQLite...")
    try:
        df = pd.read_excel(EXCEL_F, sheet_name="Daily")
        df["date"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")
        df = df.rename(columns={
            "Ticker": "ticker", "YF_Ticker": "yf_ticker",
            "Close": "close", "Volume": "volume",
            "MA_20": "ema_20", "MA_200": "ema_200",
        })
        cols = ["yf_ticker", "ticker", "date", "close", "volume", "ema_20", "ema_200"]
        df   = df[[c for c in cols if c in df.columns]]
        df.to_sql("daily", conn, if_exists="append", index=False,
                  method="multi", chunksize=5000)
        conn.commit()
        print(f"  Migrated {len(df):,} rows from Excel.")
        return True
    except Exception as e:
        print(f"  [warn] Excel migration failed: {e}. Will do fresh pull.")
        return False


# ── Main ───────────────────────────────────────────────────────────────────
def main() -> None:
    ts = datetime.now()
    print(f"\n{'='*60}")
    print(f"Sector Rotation Data Collector   {ts:%Y-%m-%d %H:%M:%S}")
    print("=" * 60)

    # 1. Industry
    print("\n[1] Loading industry classification...")
    industry   = load_industry()
    ticker_lkp = industry[["Ticker", "YF_Ticker"]].drop_duplicates("YF_Ticker")
    # Include SPX in price fetch (not in industry table)
    yf_tickers = industry["YF_Ticker"].unique().tolist() + [SPX_TICKER]
    print(f"  {len(yf_tickers) - 1} industry tickers + SPX.")

    # 2. DB init
    print("\n[2] Opening database...")
    conn = get_conn()
    init_db(conn)
    migrate_schema_to_ema(conn)
    upsert_industry(conn, industry)

    existing_rows = db_row_count(conn)
    last_date     = get_last_date(conn)
    print(f"  {existing_rows:,} existing rows. Last date: {last_date}")

    today = date.today()

    # 3. Determine fetch window
    if last_date is None:
        migrated  = migrate_from_excel(conn)
        last_date = get_last_date(conn)
        if last_date is None:
            start = (today - timedelta(days=HISTORY_DAYS)).strftime("%Y-%m-%d")
            print(f"  No data yet. Pulling {HISTORY_DAYS} days from {start}.")

    # Check whether SPX is already in the DB (may have been added later)
    spx_last = conn.execute(
        "SELECT MAX(date) FROM daily WHERE yf_ticker = ?", (SPX_TICKER,)
    ).fetchone()[0]
    spx_missing = spx_last is None

    if last_date is not None and last_date >= today and not spx_missing:
        print("\n  Price data already up to date.")
    else:
        if spx_missing and last_date is not None and last_date >= today:
            # Only SPX is missing — fetch full SPX history
            start = (today - timedelta(days=HISTORY_DAYS)).strftime("%Y-%m-%d")
            fetch_tickers = [SPX_TICKER]
            print(f"\n[3] SPX not in DB — backfilling from {start}...")
        else:
            if last_date is not None:
                start = (
                    datetime.combine(last_date, datetime.min.time()) + timedelta(days=1)
                ).strftime("%Y-%m-%d")
            fetch_tickers = yf_tickers
            print(f"\n[3] Fetching prices {start} -> {today} ...")

        end      = (today + timedelta(days=1)).strftime("%Y-%m-%d")
        new_data = fetch(fetch_tickers, start, end)

        if new_data.empty:
            print("  No new price data returned.")
        else:
            print(f"  Fetched {len(new_data):,} rows across {new_data['YF_Ticker'].nunique()} tickers.")
            print("\n[4] Computing EMAs and writing to DB...")
            inserted = compute_and_insert(conn, new_data, ticker_lkp)
            total    = db_row_count(conn)
            print(f"  Inserted {inserted:,} rows. DB total: {total:,}.")

    # 4. Monthly market cap refresh
    print("\n[5] Checking market caps...")
    if needs_cap_refresh(conn, today):
        ref_date = today.strftime("%Y-%m-%d")
        fetch_and_store_market_caps(conn, industry["YF_Ticker"].unique().tolist(), ref_date)
    else:
        print("  Market caps current — no refresh needed.")

    # 5. Group RS computation
    print("\n[6] Computing group indices and RS signals...")
    compute_group_rs(conn, industry)

    # 6. Group summary (RS rankings + performance)
    print("\n[7] Computing group summary (RS rankings + performance)...")
    compute_group_summary(conn, industry)

    conn.close()

    elapsed = int((datetime.now() - ts).total_seconds())
    print(f"\nDone in {elapsed}s.")

    with open(LOG_F, "a") as f:
        f.write(f"{ts.isoformat()} | {elapsed}s\n")


if __name__ == "__main__":
    main()
