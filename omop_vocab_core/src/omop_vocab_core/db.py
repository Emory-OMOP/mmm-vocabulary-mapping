"""DuckDB connection management for OMOP vocabulary access."""

import os
from contextlib import contextmanager
from pathlib import Path

import duckdb

DEFAULT_VOCAB_SCHEMA = "main_vocab"
DEFAULT_CDM_SCHEMA = "main_cdm"


def get_db_path() -> str:
    """Get the DuckDB database path from OHDSI_DUCKDB_PATH env var.

    Raises ValueError if the env var is not set.
    """
    path = os.environ.get("OHDSI_DUCKDB_PATH")
    if not path:
        raise ValueError(
            "OHDSI_DUCKDB_PATH environment variable is not set. "
            "Set it to the path of your DuckDB database file."
        )
    return path


def get_vocab_schema() -> str:
    return os.environ.get("OHDSI_VOCAB_SCHEMA",
           os.environ.get("OHDSI_SCHEMA", DEFAULT_VOCAB_SCHEMA))


def get_cdm_schema() -> str:
    return os.environ.get("OHDSI_CDM_SCHEMA",
           os.environ.get("OHDSI_SCHEMA", DEFAULT_CDM_SCHEMA))


@contextmanager
def get_connection():
    """Context manager for read-only DuckDB connection."""
    db_path = get_db_path()
    if not Path(db_path).exists():
        raise FileNotFoundError(
            f"DuckDB database not found at {db_path}. "
            f"Set OHDSI_DUCKDB_PATH environment variable or run dbt to create it."
        )
    conn = duckdb.connect(db_path, read_only=True)
    try:
        yield conn
    finally:
        conn.close()


def qualified_vocab_table(table_name: str) -> str:
    """Return fully qualified vocabulary table name: schema.table."""
    return f"{get_vocab_schema()}.{table_name}"


def qualified_cdm_table(table_name: str) -> str:
    """Return fully qualified CDM clinical table name: schema.table."""
    return f"{get_cdm_schema()}.{table_name}"


# Backward compatibility aliases
get_schema = get_vocab_schema
qualified_table = qualified_vocab_table
