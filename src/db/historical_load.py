"""
Initial historical data loader — AC1, AC2, AC3, AC6.

Loads at least 1 year (252 trading days) of daily historical data for
all four indicators into the database in a single atomic transaction.

AC6 (transactional rollback): the entire load is wrapped in a single
SQLite transaction. On any failure, ROLLBACK is issued — the DB is left
empty/clean and the next attempt starts fresh. No partial data is ever
silently persisted.

Constraints:
  - Only INSERT statements — no UPDATE or DELETE anywhere in this module.
  - spx_daily_high column name enforced per DEC-2026-04-18-01.
"""

import pandas as pd

from src.db.schema import get_connection, create_schema
from src.fetch.spx import fetch_spx
from src.fetch.mmth import fetch_mmth


INSERT_SQL = (
    "INSERT INTO indicators (date, spx_daily_high, spx_12d_ema, spx_25d_ema, mmth) "
    "VALUES (?, ?, ?, ?, ?)"
)


def _build_combined_df(spx_df: pd.DataFrame, mmth_series: pd.Series) -> pd.DataFrame:
    """
    Inner-join SPX and MMTH on date, returning a clean combined DataFrame.

    Args:
        spx_df: DataFrame with columns date (str YYYY-MM-DD), spx_daily_high,
                spx_12d_ema, spx_25d_ema — already trimmed to ~252 rows.
        mmth_series: pd.Series with DatetimeIndex and float MMTH values.

    Returns:
        pd.DataFrame with columns: date, spx_daily_high, spx_12d_ema, spx_25d_ema, mmth
        At least 252 rows (inner join on trading dates).

    Raises:
        RuntimeError: if fewer than 252 rows survive the inner join.
    """
    spx_df = spx_df.copy()
    spx_df["date"] = pd.to_datetime(spx_df["date"])
    spx_df = spx_df.set_index("date")

    mmth_series = mmth_series.copy()
    mmth_series.index = pd.to_datetime(mmth_series.index).normalize()

    # Trim MMTH to the 1-year window defined by the SPX DataFrame
    start_date = spx_df.index.min()
    end_date = spx_df.index.max()
    mmth_trimmed = mmth_series.loc[start_date:end_date]

    # Inner join
    combined = spx_df.join(mmth_trimmed.rename("mmth"), how="inner")
    combined = combined.dropna(subset=["spx_daily_high", "spx_12d_ema", "spx_25d_ema", "mmth"])

    if len(combined) < 252:
        raise RuntimeError(
            f"Historical load: inner join yielded only {len(combined)} rows — "
            f"need at least 252 trading days. "
            f"SPX range: {start_date.date()} to {end_date.date()}. "
            f"MMTH range: {mmth_series.index.min().date()} to {mmth_series.index.max().date()}."
        )

    combined = combined.reset_index()
    combined["date"] = combined["date"].dt.strftime("%Y-%m-%d")
    return combined[["date", "spx_daily_high", "spx_12d_ema", "spx_25d_ema", "mmth"]]


def load_historical(
    db_path: str,
    _spx_df: pd.DataFrame = None,
    _mmth_series: pd.Series = None,
) -> None:
    """
    Load at least 1 year of historical indicator data into the database.

    Wraps the entire operation in a single SQLite transaction. If anything
    fails, ROLLBACK is issued — the DB is left empty/clean and the operation
    is fully retryable.

    Args:
        db_path: Path to the SQLite database file. Created if it does not exist.
        _spx_df: (for testing only) pre-built SPX DataFrame. If None, fetches live.
        _mmth_series: (for testing only) pre-built MMTH Series. If None, fetches live.

    Raises:
        RuntimeError: on any failure, after rolling back the transaction.
                      The error message describes the cause and confirms retryability.
    """
    # Ensure the schema exists before beginning the load transaction
    create_schema(db_path)

    conn = get_connection(db_path)
    try:
        conn.execute("BEGIN")

        # Fetch data (or use injected test data)
        spx_df = _spx_df if _spx_df is not None else fetch_spx(period="2y")
        mmth_series = _mmth_series if _mmth_series is not None else fetch_mmth(period="2y")

        # Build the combined DataFrame (inner join, 1-year window)
        combined = _build_combined_df(spx_df, mmth_series)

        # INSERT all rows — no UPDATE or DELETE
        rows = [
            (
                str(row["date"]),
                float(row["spx_daily_high"]),
                float(row["spx_12d_ema"]),
                float(row["spx_25d_ema"]),
                float(row["mmth"]),
            )
            for _, row in combined.iterrows()
        ]

        conn.executemany(INSERT_SQL, rows)
        conn.execute("COMMIT")

    except Exception as e:
        conn.execute("ROLLBACK")
        raise RuntimeError(
            f"Historical load failed — DB rolled back. Retryable. Cause: {e}"
        ) from e
    finally:
        conn.close()
