"""Core logic for OMOP concept search."""

from .db import get_connection, qualified_vocab_table
from .formatting import rows_to_dicts, MAX_RESULTS


_CONCEPT_COLUMNS = [
    "concept_id", "concept_name", "domain_id", "vocabulary_id",
    "concept_class_id", "standard_concept", "concept_code", "invalid_reason",
]

_CONCEPT_SELECT = """
    c.concept_id, c.concept_name, c.domain_id, c.vocabulary_id,
    c.concept_class_id, c.standard_concept, c.concept_code, c.invalid_reason
"""


def _build_concept_filters(
    domain: str | None,
    vocabulary_id: str | None,
    concept_class: str | None,
    standard_only: bool,
    valid_only: bool,
) -> tuple[list[str], list]:
    """Build WHERE conditions and params for concept table filters."""
    conditions: list[str] = []
    params: list = []
    if domain:
        conditions.append("c.domain_id ILIKE ?")
        params.append(domain)
    if vocabulary_id:
        conditions.append("c.vocabulary_id ILIKE ?")
        params.append(vocabulary_id)
    if concept_class:
        conditions.append("c.concept_class_id ILIKE ?")
        params.append(concept_class)
    if standard_only:
        conditions.append("c.standard_concept = 'S'")
    if valid_only:
        conditions.append("c.invalid_reason IS NULL")
    return conditions, params


def search_concepts_core(
    keyword: str,
    domain: str | None = None,
    vocabulary_id: str | None = None,
    concept_class: str | None = None,
    standard_only: bool = True,
    valid_only: bool = True,
    include_synonyms: bool = False,
    limit: int = 25,
) -> list[dict]:
    """Search OMOP vocabulary concepts by keyword with optional filters.

    Returns list of dicts with keys: concept_id, concept_name, domain_id,
    vocabulary_id, concept_class_id, standard_concept, concept_code, invalid_reason.

    When include_synonyms is True, also searches the CONCEPT_SYNONYM table
    and deduplicates by concept_id (keeping the best match).
    """
    limit = min(max(1, limit), MAX_RESULTS)
    filters, filter_params = _build_concept_filters(
        domain, vocabulary_id, concept_class, standard_only, valid_only,
    )

    # Primary: search concept_name
    name_conditions = ["c.concept_name ILIKE ?"] + filters
    name_where = " AND ".join(name_conditions)
    name_params = [f"%{keyword}%"] + filter_params

    if not include_synonyms:
        sql = f"""
            SELECT {_CONCEPT_SELECT}
            FROM {qualified_vocab_table('concept')} c
            WHERE {name_where}
            ORDER BY
                CASE WHEN c.concept_name ILIKE ? THEN 0 ELSE 1 END,
                length(c.concept_name),
                c.concept_name
            LIMIT ?
        """
        all_params = name_params + [keyword, limit]
        with get_connection() as conn:
            results = conn.execute(sql, all_params).fetchall()
        return rows_to_dicts(results, _CONCEPT_COLUMNS)

    # With synonyms: UNION name matches and synonym matches, deduplicate
    syn_conditions = ["cs.concept_synonym_name ILIKE ?"] + filters
    syn_where = " AND ".join(syn_conditions)
    syn_params = [f"%{keyword}%"] + filter_params

    sql = f"""
        WITH matches AS (
            SELECT {_CONCEPT_SELECT}, 0 AS match_source
            FROM {qualified_vocab_table('concept')} c
            WHERE {name_where}
            UNION ALL
            SELECT {_CONCEPT_SELECT}, 1 AS match_source
            FROM {qualified_vocab_table('concept_synonym')} cs
            JOIN {qualified_vocab_table('concept')} c ON cs.concept_id = c.concept_id
            WHERE {syn_where}
        )
        SELECT concept_id, concept_name, domain_id, vocabulary_id,
               concept_class_id, standard_concept, concept_code, invalid_reason
        FROM (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY concept_id
                ORDER BY match_source, length(concept_name)
            ) AS rn
            FROM matches
        )
        WHERE rn = 1
        ORDER BY
            match_source,
            CASE WHEN concept_name ILIKE ? THEN 0 ELSE 1 END,
            length(concept_name),
            concept_name
        LIMIT ?
    """
    all_params = name_params + syn_params + [keyword, limit]
    with get_connection() as conn:
        results = conn.execute(sql, all_params).fetchall()
    return rows_to_dicts(results, _CONCEPT_COLUMNS)
