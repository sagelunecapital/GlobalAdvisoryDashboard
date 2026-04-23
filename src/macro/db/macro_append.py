"""
Macro indicator append operation — AC5, AC8.

Appends a batch of (indicator_id, date, value, fetch_timestamp) records to
the macro_indicators table using INSERT OR IGNORE — idempotent on (indicator_id, date).

Constraints:
  - INSERT OR IGNORE only — no UPDATE or DELETE.
  - Returns count of rows actually inserted (not skipped duplicates).
"""

from src.macro.db.macro_schema import get_macro_connection, create_macro_schema


INSERT_SQL = (
    "INSERT OR IGNORE INTO macro_indicators "
    "(indicator_id, date, value, fetch_timestamp) "
    "VALUES (?, ?, ?, ?)"
)


def append_macro_records(
    db_path: str,
    records: list,
) -> int:
    """
    Append a batch of macro indicator records to the database.

    Args:
        db_path: Path to the SQLite database file.
        records: List of tuples (indicator_id, date, value, fetch_timestamp).
                 - indicator_id: str — named indicator (e.g., 'US_10Y_YIELD')
                 - date: str — ISO-8601 YYYY-MM-DD
                 - value: float — numeric observation
                 - fetch_timestamp: str — UTC ISO-8601 fetch time

    Returns:
        Number of rows actually inserted (duplicate (indicator_id, date) pairs
        are silently skipped via INSERT OR IGNORE and are NOT counted).

    Raises:
        RuntimeError: if the database cannot be opened or the insert fails.
    """
    create_macro_schema(db_path)

    conn = get_macro_connection(db_path)
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
        raise RuntimeError(f"macro append failed: {e}") from e
    finally:
        conn.close()
