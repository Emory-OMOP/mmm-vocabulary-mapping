"""Shim — re-exports from omop_vocab_core.

Keeps backward compatibility for any code importing from `db` directly
via the sys.path hack in server.py.
"""
from omop_vocab_core.db import (  # noqa: F401
    get_connection,
    get_db_path,
    get_vocab_schema,
    get_cdm_schema,
    qualified_vocab_table,
    qualified_cdm_table,
    get_schema,
    qualified_table,
    DEFAULT_VOCAB_SCHEMA,
    DEFAULT_CDM_SCHEMA,
)
