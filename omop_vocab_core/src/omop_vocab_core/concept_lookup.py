"""Core logic for direct concept_id lookup."""

from .db import get_connection, qualified_vocab_table
from .formatting import rows_to_dicts

CONCEPT_COLUMNS = [
    "concept_id", "concept_name", "domain_id", "vocabulary_id",
    "concept_class_id", "standard_concept", "concept_code", "invalid_reason",
]


def get_concept_core(concept_ids: list[int]) -> list[dict]:
    """Look up one or more concepts by concept_id.

    Returns list of dicts with keys matching CONCEPT_COLUMNS.
    Results are ordered to match the input concept_ids list.
    """
    if not concept_ids:
        return []

    placeholders = ", ".join("?" for _ in concept_ids)

    sql = f"""
        SELECT
            c.concept_id,
            c.concept_name,
            c.domain_id,
            c.vocabulary_id,
            c.concept_class_id,
            c.standard_concept,
            c.concept_code,
            c.invalid_reason
        FROM {qualified_vocab_table('concept')} c
        WHERE c.concept_id IN ({placeholders})
        ORDER BY c.concept_id
    """

    with get_connection() as conn:
        results = conn.execute(sql, concept_ids).fetchall()

    return rows_to_dicts(results, CONCEPT_COLUMNS)
