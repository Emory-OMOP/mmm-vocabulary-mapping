"""Trace non-standard concepts to their standard equivalents via Maps to chains."""

from __future__ import annotations

from .db import get_connection, qualified_vocab_table
from .formatting import rows_to_dicts


def trace_standard_mapping_core(
    concept_id: int,
    max_hops: int = 3,
) -> dict:
    """Follow 'Maps to' relationship chain from a concept to its standard equivalent.

    Returns a dict with:
    - source: the input concept metadata
    - target: the standard concept reached (or None if already standard / no mapping)
    - chain: list of intermediate steps [{concept, relationship_id}, ...]
    - hops: number of mapping steps followed
    """
    max_hops = min(max(1, max_hops), 5)

    columns = [
        "concept_id", "concept_name", "domain_id", "vocabulary_id",
        "concept_class_id", "standard_concept", "concept_code", "invalid_reason",
    ]
    col_select = ", ".join(f"c.{col}" for col in columns)

    with get_connection() as conn:
        # Fetch the source concept
        source_row = conn.execute(
            f"SELECT {col_select} FROM {qualified_vocab_table('concept')} c WHERE c.concept_id = ?",
            [concept_id],
        ).fetchone()

        if not source_row:
            return {"source": None, "target": None, "chain": [], "hops": 0,
                    "error": f"Concept {concept_id} not found"}

        source = dict(zip(columns, source_row))

        # If already standard, return immediately
        if source.get("standard_concept") == "S":
            return {"source": source, "target": source, "chain": [], "hops": 0}

        # Follow Maps to chain
        chain = []
        current_id = concept_id
        visited = {concept_id}

        for hop in range(max_hops):
            row = conn.execute(f"""
                SELECT cr.relationship_id, {col_select}
                FROM {qualified_vocab_table('concept_relationship')} cr
                JOIN {qualified_vocab_table('concept')} c ON cr.concept_id_2 = c.concept_id
                WHERE cr.concept_id_1 = ?
                  AND cr.relationship_id = 'Maps to'
                  AND cr.invalid_reason IS NULL
                  AND c.concept_id != ?
                LIMIT 1
            """, [current_id, current_id]).fetchone()

            if not row:
                break

            rel_id = row[0]
            mapped_concept = dict(zip(columns, row[1:]))
            chain.append({
                "relationship_id": rel_id,
                "concept": mapped_concept,
            })

            if mapped_concept.get("standard_concept") == "S":
                return {
                    "source": source,
                    "target": mapped_concept,
                    "chain": chain,
                    "hops": len(chain),
                }

            next_id = mapped_concept["concept_id"]
            if next_id in visited:
                break
            visited.add(next_id)
            current_id = next_id

        # No standard concept found
        last = chain[-1]["concept"] if chain else source
        return {
            "source": source,
            "target": None,
            "chain": chain,
            "hops": len(chain),
            "error": f"No standard concept found after {len(chain)} hop(s). Last: {last.get('concept_name')} ({last.get('concept_id')})",
        }
