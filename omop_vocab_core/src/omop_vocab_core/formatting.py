"""Shared data formatting utilities."""

MAX_RESULTS = 50


def rows_to_dicts(cursor_result, column_names: list[str]) -> list[dict]:
    """Convert DuckDB fetchall result to list of dicts."""
    return [dict(zip(column_names, row)) for row in cursor_result]
