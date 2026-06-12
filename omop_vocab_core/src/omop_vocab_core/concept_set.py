"""Core logic for OMOP concept set resolution/preview."""

from .db import get_connection, qualified_vocab_table
from .formatting import rows_to_dicts, MAX_RESULTS


def preview_concept_set_core(
    concept_ids: list[int],
    include_descendants: bool = True,
    limit: int = 50,
) -> tuple[list[dict], int]:
    """Resolve a concept set by expanding concept_ids with optional descendants.

    Returns (rows, total_count) where rows is a list of dicts with keys:
    concept_id, concept_name, domain_id, vocabulary_id, concept_class_id,
    standard_concept, concept_code, is_descendant.
    """
    if not concept_ids:
        return [], 0

    limit = min(max(1, limit), MAX_RESULTS)
    placeholders = ", ".join(["?"] * len(concept_ids))

    if include_descendants:
        sql = f"""
            WITH input_concepts AS (
                SELECT unnest([{placeholders}]) AS concept_id
            ),
            resolved AS (
                SELECT DISTINCT c.concept_id, c.concept_name, c.domain_id,
                       c.vocabulary_id, c.concept_class_id, c.standard_concept,
                       c.concept_code, 0 AS is_descendant
                FROM {qualified_vocab_table('concept')} c
                WHERE c.concept_id IN (SELECT concept_id FROM input_concepts)
                  AND c.invalid_reason IS NULL

                UNION

                SELECT DISTINCT c.concept_id, c.concept_name, c.domain_id,
                       c.vocabulary_id, c.concept_class_id, c.standard_concept,
                       c.concept_code, 1 AS is_descendant
                FROM {qualified_vocab_table('concept_ancestor')} ca
                JOIN {qualified_vocab_table('concept')} c
                    ON ca.descendant_concept_id = c.concept_id
                WHERE ca.ancestor_concept_id IN (SELECT concept_id FROM input_concepts)
                  AND ca.min_levels_of_separation > 0
                  AND c.invalid_reason IS NULL
                  AND c.standard_concept = 'S'
            )
            SELECT concept_id, concept_name, domain_id, vocabulary_id,
                   concept_class_id, standard_concept, concept_code,
                   MIN(is_descendant) AS is_descendant
            FROM resolved
            GROUP BY concept_id, concept_name, domain_id, vocabulary_id,
                     concept_class_id, standard_concept, concept_code
            ORDER BY is_descendant, concept_name
            LIMIT ?
        """
        params = list(concept_ids) + [limit]
    else:
        sql = f"""
            SELECT c.concept_id, c.concept_name, c.domain_id,
                   c.vocabulary_id, c.concept_class_id, c.standard_concept,
                   c.concept_code, 0 AS is_descendant
            FROM {qualified_vocab_table('concept')} c
            WHERE c.concept_id IN ({placeholders})
              AND c.invalid_reason IS NULL
            ORDER BY c.concept_name
            LIMIT ?
        """
        params = list(concept_ids) + [limit]

    columns = [
        "concept_id", "concept_name", "domain_id", "vocabulary_id",
        "concept_class_id", "standard_concept", "concept_code", "is_descendant",
    ]

    with get_connection() as conn:
        results = conn.execute(sql, params).fetchall()

        if include_descendants:
            count_sql = f"""
                SELECT COUNT(DISTINCT c.concept_id)
                FROM {qualified_vocab_table('concept_ancestor')} ca
                JOIN {qualified_vocab_table('concept')} c
                    ON ca.descendant_concept_id = c.concept_id
                WHERE ca.ancestor_concept_id IN ({placeholders})
                  AND c.invalid_reason IS NULL
                  AND c.standard_concept = 'S'
            """
            total_count = conn.execute(count_sql, list(concept_ids)).fetchone()[0]
        else:
            total_count = len(results)

    return rows_to_dicts(results, columns), total_count
