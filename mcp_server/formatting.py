"""Formatting utilities for MCP tool results.

rows_to_dicts and MAX_RESULTS re-exported from omop_vocab_core.
format_concept_table stays here — it's MCP presentation-layer code.
"""

from omop_vocab_core.formatting import rows_to_dicts, MAX_RESULTS  # noqa: F401


def format_concept_table(rows: list[dict], header: str = "") -> str:
    """Format a list of concept rows as a markdown table."""
    if not rows:
        return f"{header}\n\nNo results found." if header else "No results found."

    lines = []
    if header:
        lines.append(header)
        lines.append("")

    lines.append(
        "| concept_id | concept_name | domain_id | vocabulary_id | "
        "concept_class_id | standard_concept | concept_code |"
    )
    lines.append(
        "|:-----------|:-------------|:----------|:--------------|"
        ":-----------------|:-----------------|:-------------|"
    )

    for r in rows:
        std = r.get("standard_concept") or ""
        name = r["concept_name"][:60]
        lines.append(
            f"| {r['concept_id']} | {name} | {r['domain_id']} | "
            f"{r['vocabulary_id']} | {r['concept_class_id']} | {std} | "
            f"{r['concept_code']} |"
        )

    lines.append(f"\n*{len(rows)} result(s) returned.*")
    return "\n".join(lines)
