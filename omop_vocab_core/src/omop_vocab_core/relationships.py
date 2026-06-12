"""Core logic for OMOP concept relationship lookups."""

from .db import get_connection, qualified_vocab_table
from .formatting import rows_to_dicts, MAX_RESULTS


def get_relationships_core(
    concept_id: int,
    relationship_id: str | None = None,
    valid_only: bool = True,
    limit: int = 50,
) -> tuple[list[dict], str, str]:
    """Get relationships for a concept.

    Returns (rows, source_name, source_vocab) where rows is a list of dicts
    with keys: relationship_id, related_concept_id, related_concept_name,
    domain_id, vocabulary_id, concept_class_id, standard_concept, concept_code.
    """
    limit = min(max(1, limit), MAX_RESULTS)

    conditions = ["cr.concept_id_1 = ?"]
    params: list = [concept_id]

    if relationship_id:
        conditions.append("cr.relationship_id ILIKE ?")
        params.append(relationship_id)

    if valid_only:
        conditions.append("cr.invalid_reason IS NULL")

    where = " AND ".join(conditions)
    params.append(limit)

    sql = f"""
        SELECT
            cr.relationship_id,
            c2.concept_id AS related_concept_id,
            c2.concept_name AS related_concept_name,
            c2.domain_id,
            c2.vocabulary_id,
            c2.concept_class_id,
            c2.standard_concept,
            c2.concept_code
        FROM {qualified_vocab_table('concept_relationship')} cr
        JOIN {qualified_vocab_table('concept')} c2
            ON cr.concept_id_2 = c2.concept_id
        WHERE {where}
        ORDER BY cr.relationship_id, c2.concept_name
        LIMIT ?
    """

    columns = [
        "relationship_id", "related_concept_id", "related_concept_name",
        "domain_id", "vocabulary_id", "concept_class_id",
        "standard_concept", "concept_code",
    ]

    with get_connection() as conn:
        source = conn.execute(
            f"SELECT concept_name, vocabulary_id FROM {qualified_vocab_table('concept')} WHERE concept_id = ?",
            [concept_id],
        ).fetchone()
        source_name = source[0] if source else f"Unknown ({concept_id})"
        source_vocab = source[1] if source else "?"

        results = conn.execute(sql, params).fetchall()

    return rows_to_dicts(results, columns), source_name, source_vocab
