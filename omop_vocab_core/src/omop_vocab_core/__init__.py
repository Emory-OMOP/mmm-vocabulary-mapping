"""Shared OMOP vocabulary query library.

Provides DuckDB-backed concept search, lookup, hierarchy traversal,
relationship queries, and concept set resolution. No MCP dependencies —
intended as a shared foundation for multiple MCP servers.
"""

from .db import (
    get_connection,
    get_db_path,
    get_vocab_schema,
    get_cdm_schema,
    qualified_vocab_table,
    qualified_cdm_table,
)
from .formatting import rows_to_dicts, MAX_RESULTS
from .search import search_concepts_core
from .concept_lookup import get_concept_core, CONCEPT_COLUMNS
from .hierarchy import get_ancestors_core, get_descendants_core
from .relationships import get_relationships_core
from .concept_set import preview_concept_set_core
from .table_schema import list_cdm_tables_core, get_table_schema_core
from .staging import (
    get_staging_connection,
    init_staging_db,
    create_result,
    add_result_concepts,
    get_result,
    get_result_concepts,
    cherry_pick,
    promote_result,
    list_results,
    list_drafts,
    get_draft_concept_ids,
    get_result_lineage,
    cleanup_ephemeral,
)

__all__ = [
    # db
    "get_connection",
    "get_db_path",
    "get_vocab_schema",
    "get_cdm_schema",
    "qualified_vocab_table",
    "qualified_cdm_table",
    # formatting
    "rows_to_dicts",
    "MAX_RESULTS",
    # search
    "search_concepts_core",
    # concept lookup
    "get_concept_core",
    "CONCEPT_COLUMNS",
    # hierarchy
    "get_ancestors_core",
    "get_descendants_core",
    # relationships
    "get_relationships_core",
    # concept set
    "preview_concept_set_core",
    # table schema
    "list_cdm_tables_core",
    "get_table_schema_core",
    # staging
    "get_staging_connection",
    "init_staging_db",
    "create_result",
    "add_result_concepts",
    "get_result",
    "get_result_concepts",
    "cherry_pick",
    "promote_result",
    "list_results",
    "list_drafts",
    "get_draft_concept_ids",
    "get_result_lineage",
    "cleanup_ephemeral",
]
