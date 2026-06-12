"""get_concept tool: Look up OMOP concepts directly by concept_id."""

from mcp.server.fastmcp import FastMCP

from omop_vocab_core.concept_lookup import get_concept_core
from tools._staging_mixin import stage_concepts, format_staged_table


def register_concept_lookup(mcp: FastMCP):

    @mcp.tool()
    async def get_concept(
        concept_ids: list[int],
    ) -> str:
        """Look up one or more OMOP concepts by concept_id.

        Use this tool when you already have a concept_id and need its metadata
        (name, domain, vocabulary, concept class, standard status, etc.).
        Accepts a list to support batch lookups.

        This is the fastest way to retrieve concept details — prefer this over
        search_concepts when you already know the concept_id(s).

        Args:
            concept_ids: One or more OMOP concept_ids to look up (e.g., [201826] or [201826, 4329847])
        """
        rows = get_concept_core(concept_ids)

        found_ids = {r["concept_id"] for r in rows}
        missing = [cid for cid in concept_ids if cid not in found_ids]

        result_id = stage_concepts(
            "get_concept", {"concept_ids": concept_ids}, rows,
        )

        if not rows:
            result = "## Concept Lookup (0 found)\n\nNo results found."
        else:
            result = format_staged_table(
                result_id, rows,
                header=f"## Concept Lookup ({len(rows)} found)",
            )

        if missing:
            result += f"\n\n**Not found:** {', '.join(str(m) for m in missing)}"

        return result
