"""Raw DuckDB SQL queries for graph traversal over OMOP vocabulary tables."""

from __future__ import annotations

from .db import qualified_vocab_table
from .formatting import rows_to_dicts


# Column lists for reuse
_CONCEPT_COLS = [
    "concept_id", "concept_name", "concept_code", "vocabulary_id",
    "domain_id", "concept_class_id", "standard_concept", "invalid_reason",
]

_PREDICATE_COLS = [
    "relationship_id", "relationship_name", "reverse_relationship_id",
    "is_hierarchical", "defines_ancestry",
]

_EDGE_COLS = ["concept_id_1", "relationship_id", "concept_id_2"]


def _in_placeholders(ids: list) -> str:
    """Build a comma-separated placeholder string for IN clauses."""
    return ", ".join("?" for _ in ids)


def fetch_all_predicates(conn) -> list[dict]:
    """Load all rows from the RELATIONSHIP table (typically ~700 rows)."""
    sql = f"""
        SELECT {', '.join(_PREDICATE_COLS)}
        FROM {qualified_vocab_table('relationship')}
    """
    rows = conn.execute(sql).fetchall()
    return rows_to_dicts(rows, _PREDICATE_COLS)


def fetch_concept_batch(conn, concept_ids: list[int]) -> list[dict]:
    """Fetch concept metadata for a batch of concept_ids."""
    if not concept_ids:
        return []
    placeholders = _in_placeholders(concept_ids)
    sql = f"""
        SELECT {', '.join(_CONCEPT_COLS)}
        FROM {qualified_vocab_table('concept')}
        WHERE concept_id IN ({placeholders})
    """
    rows = conn.execute(sql, concept_ids).fetchall()
    return rows_to_dicts(rows, _CONCEPT_COLS)


def fetch_outgoing_edges(
    conn,
    concept_ids: list[int],
    relationship_ids: list[str] | None = None,
) -> list[tuple]:
    """Fetch outgoing edges for a batch of source concept_ids.

    Returns raw tuples of (concept_id_1, relationship_id, concept_id_2).
    """
    if not concept_ids:
        return []
    params: list = list(concept_ids)
    where = f"cr.concept_id_1 IN ({_in_placeholders(concept_ids)}) AND cr.invalid_reason IS NULL"

    if relationship_ids:
        where += f" AND cr.relationship_id IN ({_in_placeholders(relationship_ids)})"
        params.extend(relationship_ids)

    sql = f"""
        SELECT {', '.join('cr.' + c for c in _EDGE_COLS)}
        FROM {qualified_vocab_table('concept_relationship')} cr
        WHERE {where}
    """
    return conn.execute(sql, params).fetchall()


def fetch_incoming_edges(
    conn,
    concept_ids: list[int],
    relationship_ids: list[str] | None = None,
) -> list[tuple]:
    """Fetch incoming edges for a batch of target concept_ids.

    Returns raw tuples of (concept_id_1, relationship_id, concept_id_2).
    """
    if not concept_ids:
        return []
    params: list = list(concept_ids)
    where = f"cr.concept_id_2 IN ({_in_placeholders(concept_ids)}) AND cr.invalid_reason IS NULL"

    if relationship_ids:
        where += f" AND cr.relationship_id IN ({_in_placeholders(relationship_ids)})"
        params.extend(relationship_ids)

    sql = f"""
        SELECT {', '.join('cr.' + c for c in _EDGE_COLS)}
        FROM {qualified_vocab_table('concept_relationship')} cr
        WHERE {where}
    """
    return conn.execute(sql, params).fetchall()


def fetch_ancestor_check(
    conn, ancestor_id: int, descendant_id: int
) -> int | None:
    """Check if ancestor_id is an ancestor of descendant_id.

    Returns min_levels_of_separation if relationship exists, None otherwise.
    """
    sql = f"""
        SELECT min_levels_of_separation
        FROM {qualified_vocab_table('concept_ancestor')}
        WHERE ancestor_concept_id = ?
          AND descendant_concept_id = ?
          AND min_levels_of_separation > 0
        LIMIT 1
    """
    row = conn.execute(sql, [ancestor_id, descendant_id]).fetchone()
    return row[0] if row else None
