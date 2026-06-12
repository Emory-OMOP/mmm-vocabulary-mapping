"""Core logic for OMOP concept hierarchy traversal."""

from .db import get_connection, qualified_vocab_table
from .formatting import rows_to_dicts, MAX_RESULTS


def get_concept_name(conn, concept_id: int) -> str:
    """Look up a concept name by ID using an existing connection."""
    result = conn.execute(
        f"SELECT concept_name FROM {qualified_vocab_table('concept')} WHERE concept_id = ?",
        [concept_id],
    ).fetchone()
    return result[0] if result else f"Unknown ({concept_id})"


def get_ancestors_core(
    concept_id: int,
    max_separation: int | None = None,
    limit: int = 50,
) -> tuple[list[dict], str]:
    """Get ancestor concepts of a given concept.

    Returns (rows, source_name) where rows is a list of dicts with keys:
    concept_id, concept_name, domain_id, vocabulary_id, concept_class_id,
    standard_concept, concept_code, min_separation, max_separation.
    """
    limit = min(max(1, limit), MAX_RESULTS)

    conditions = ["ca.descendant_concept_id = ?", "ca.min_levels_of_separation > 0"]
    params: list = [concept_id]

    if max_separation is not None:
        conditions.append("ca.min_levels_of_separation <= ?")
        params.append(max_separation)

    where = " AND ".join(conditions)
    params.append(limit)

    sql = f"""
        SELECT
            c.concept_id,
            c.concept_name,
            c.domain_id,
            c.vocabulary_id,
            c.concept_class_id,
            c.standard_concept,
            c.concept_code,
            ca.min_levels_of_separation,
            ca.max_levels_of_separation
        FROM {qualified_vocab_table('concept_ancestor')} ca
        JOIN {qualified_vocab_table('concept')} c
            ON ca.ancestor_concept_id = c.concept_id
        WHERE {where}
        ORDER BY ca.min_levels_of_separation ASC
        LIMIT ?
    """

    columns = [
        "concept_id", "concept_name", "domain_id", "vocabulary_id",
        "concept_class_id", "standard_concept", "concept_code",
        "min_separation", "max_separation",
    ]

    with get_connection() as conn:
        source_name = get_concept_name(conn, concept_id)
        results = conn.execute(sql, params).fetchall()

    return rows_to_dicts(results, columns), source_name


def get_descendants_core(
    concept_id: int,
    max_separation: int | None = None,
    limit: int = 50,
) -> tuple[list[dict], str]:
    """Get descendant concepts of a given concept.

    Returns (rows, source_name) where rows is a list of dicts with keys:
    concept_id, concept_name, domain_id, vocabulary_id, concept_class_id,
    standard_concept, concept_code, min_separation, max_separation.
    """
    limit = min(max(1, limit), MAX_RESULTS)

    conditions = ["ca.ancestor_concept_id = ?", "ca.min_levels_of_separation > 0"]
    params: list = [concept_id]

    if max_separation is not None:
        conditions.append("ca.min_levels_of_separation <= ?")
        params.append(max_separation)

    where = " AND ".join(conditions)
    params.append(limit)

    sql = f"""
        SELECT
            c.concept_id,
            c.concept_name,
            c.domain_id,
            c.vocabulary_id,
            c.concept_class_id,
            c.standard_concept,
            c.concept_code,
            ca.min_levels_of_separation,
            ca.max_levels_of_separation
        FROM {qualified_vocab_table('concept_ancestor')} ca
        JOIN {qualified_vocab_table('concept')} c
            ON ca.descendant_concept_id = c.concept_id
        WHERE {where}
        ORDER BY ca.min_levels_of_separation ASC, c.concept_name
        LIMIT ?
    """

    columns = [
        "concept_id", "concept_name", "domain_id", "vocabulary_id",
        "concept_class_id", "standard_concept", "concept_code",
        "min_separation", "max_separation",
    ]

    with get_connection() as conn:
        source_name = get_concept_name(conn, concept_id)
        results = conn.execute(sql, params).fetchall()

    return rows_to_dicts(results, columns), source_name
