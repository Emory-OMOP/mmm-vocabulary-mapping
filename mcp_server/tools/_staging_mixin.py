"""Shared auto-staging helper for concept-returning tools.

Every concept-returning tool stages its results in the session-level DuckDB
so that concept_ids flow through the database — never through the LLM context.
The LLM sees concept names and row indices; it references results by result_id.
"""

import json
from omop_vocab_core.staging import (
    init_staging_db,
    create_result,
    add_result_concepts,
)

# Ensure staging DB exists on import
init_staging_db()


def stage_concepts(
    tool_name: str,
    parameters: dict,
    concepts: list[dict],
    parent_result_id: int | None = None,
) -> int | None:
    """Stage a list of concept dicts and return the result_id.

    Each dict in *concepts* MUST have a ``concept_id`` key.  Additional keys
    (concept_name, domain_id, vocabulary_id, concept_class_id, concept_code,
    standard_concept, include_descendants, include_mapped, is_excluded,
    is_descendant, source_concept_id) are stored if present.

    Returns None when *concepts* is empty.
    """
    if not concepts:
        return None

    result_id = create_result(
        tool_name=tool_name,
        parameters=json.loads(json.dumps(parameters, default=str)),
        parent_result_id=parent_result_id,
    )
    add_result_concepts(result_id, concepts)
    return result_id


def result_id_line(result_id: int | None) -> str:
    """Return a consistent footer identifying the staged result."""
    if result_id is None:
        return "\n*result_id: none*"
    return f"\n*result_id: {result_id}*"


def format_staged_table(
    result_id: int,
    concepts: list[dict],
    header: str = "",
    columns: list[tuple[str, str]] | None = None,
) -> str:
    """Default markdown table formatted WITHOUT concept_ids.

    Args:
        result_id: The staging result_id.
        concepts: Original concept dicts (concept_id will be stripped from display).
        header: Optional header line.
        columns: Optional list of (key, display_label) pairs for columns.
                 Defaults to standard concept fields.
    """
    if columns is None:
        columns = [
            ("concept_name", "concept_name"),
            ("domain_id", "domain"),
            ("vocabulary_id", "vocab"),
            ("concept_class_id", "class"),
            ("standard_concept", "std"),
            ("concept_code", "code"),
        ]

    lines = []
    if header:
        lines.append(header)
        lines.append("")

    lines.append(f"**{len(concepts)} concepts** (result_id: {result_id})")
    lines.append("")

    # Table header
    col_headers = ["#"] + [label for _, label in columns]
    lines.append("| " + " | ".join(col_headers) + " |")
    lines.append("|" + "|".join("---" for _ in range(len(col_headers))) + "|")

    for idx, c in enumerate(concepts):
        vals = [str(idx)]
        for key, _ in columns:
            v = c.get(key, "")
            if v is None:
                v = ""
            v = str(v)[:60]
            vals.append(v)
        lines.append("| " + " | ".join(vals) + " |")

    lines.append(result_id_line(result_id))
    return "\n".join(lines)
