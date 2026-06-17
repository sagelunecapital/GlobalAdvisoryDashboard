"""
Liquidity series append operation -- AC5, AC8.

Appends a batch of (series_id, date, value, fetch_timestamp) records to
the liquidity_series table using INSERT OR IGNORE -- idempotent on (series_id, date).

Constraints:
  - INSERT OR IGNORE only -- no UPDATE or DELETE.
  - Returns count of rows actually inserted (not skipped duplicates).
"""

from src.liquidity.db.liquidity_schema import get_liquidity_connection, create_liquidity_schema


INSERT_SQL = (
    "INSERT OR IGNORE INTO liquidity_series "
    "(series_id, date, value, fetch_timestamp) "
    "VALUES (?, ?, ?, ?)"
)


def append_liquidity_records(
    db_path: str,
    records: list,
) -> int:
    """
    Append a batch of liquidity series records to the database.

    Args:
        db_path: Path to the SQLite database file.
        records: List of tuples (series_id, date, value, fetch_timestamp).
                 - series_id: str -- named series (e.g., 'WRESBAL', 'BTC_WEEKLY')
                 - date: str -- ISO-8601 YYYY-MM-DD
                 - value: float -- numeric observation
                 - fetch_timestamp: str -- UTC ISO-8601 fetch time

    Returns:
        Number of rows actually inserted (duplicate (series_id, date) pairs
        are silently skipped via INSERT OR IGNORE and are NOT counted).

    Raises:
        RuntimeError: if the database cannot be opened or the insert fails.
    """
    create_liquidity_schema(db_path)

    conn = get_liquidity_connection(db_path)
    try:
        conn.execute("BEGIN")
        cursor = conn.cursor()
        inserted = 0
        for record in records:
            cursor.execute(INSERT_SQL, record)
            inserted += cursor.rowcount
        conn.execute("COMMIT")
        return inserted
    except Exception as e:
        conn.execute("ROLLBACK")
        raise RuntimeError(f"liquidity append failed: {e}") from e
    finally:
        conn.close()


def get_latest_date(db_path: str, series_id: str) -> str | None:
    """
    Return the latest stored date (YYYY-MM-DD) for the given series_id,
    or None if no records exist yet.

    Used for incremental fetch (AC5): caller fetches only dates after this date.
    """
    create_liquidity_schema(db_path)
    conn = get_liquidity_connection(db_path)
    try:
        row = conn.execute(
            "SELECT MAX(date) FROM liquidity_series WHERE series_id = ?",
            (series_id,),
        ).fetchone()
        return row[0] if row and row[0] is not None else None
    finally:
        conn.close()
