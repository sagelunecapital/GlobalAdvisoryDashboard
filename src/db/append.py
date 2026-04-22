"""
Daily append operation — AC4.

Appends a single day's indicator values to the database.

Constraints:
  - Uses INSERT OR IGNORE — idempotent; duplicate dates are silently skipped (AC4).
  - No UPDATE or DELETE SQL — append-only per AC3.
  - Closes the connection after each call so data is durably persisted (AC5).
"""

from src.db.schema import get_connection, create_schema


INSERT_SQL = (
    "INSERT OR IGNORE INTO indicators "
    "(date, spx_daily_high, spx_12d_ema, spx_25d_ema, mmth) "
    "VALUES (?, ?, ?, ?, ?)"
)


def append_day(
    db_path: str,
    date: str,
    spx_daily_high: float,
    spx_12d_ema: float,
    spx_25d_ema: float,
    mmth: float,
) -> None:
    """
    Append one day's indicator values to the database.

    Idempotent: if a record with the same date already exists, the call
    is silently skipped (INSERT OR IGNORE). This ensures append-only
    semantics even when called multiple times for the same day.

    Args:
        db_path:       Path to the SQLite database file.
        date:          ISO-8601 date string (YYYY-MM-DD).
        spx_daily_high: SPX daily HIGH price (DEC-2026-04-18-01).
        spx_12d_ema:   12-day EMA of spx_daily_high.
        spx_25d_ema:   25-day EMA of spx_daily_high.
        mmth:          % NYSE stocks above 200-day moving average.

    Raises:
        RuntimeError: if the database cannot be opened or the insert fails.
    """
    # Ensure schema exists (idempotent)
    create_schema(db_path)

    conn = get_connection(db_path)
    try:
        conn.execute(
            INSERT_SQL,
            (date, spx_daily_high, spx_12d_ema, spx_25d_ema, mmth),
        )
        conn.commit()
    finally:
        conn.close()
