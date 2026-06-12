"""preview_concept_set tool: Resolve concept sets with optional descendant inclusion."""

from mcp.server.fastmcp import FastMCP

from omop_vocab_core.concept_set import preview_concept_set_core
from tools._staging_mixin import stage_concepts, result_id_line


def register_concept_set_tools(mcp: FastMCP):

    @mcp.tool()
    async def preview_concept_set(
        concept_ids: list[int],
        include_descendants: bool = True,
        limit: int = 50,
    ) -> str:
        """Preview/resolve a concept set by expanding concept_ids with their descendants.

        Given a list of concept_ids, resolves the full concept set by optionally
        including all descendant concepts from the CONCEPT_ANCESTOR table.
        This is the core operation behind OHDSI cohort definitions — use it to
        verify which concepts will be included before building a cohort.

        After previewing a concept set here, use the result_id to reference
        this staged result for downstream operations (cherry-pick, promote,
        or feed into cohort compiler tools).

        Args:
            concept_ids: List of OMOP concept_ids to include in the set
            include_descendants: If True, include all descendants of each concept. Default: True
            limit: Maximum total concepts to return (1-50). Default: 50
        """
        if not concept_ids:
            return "Error: concept_ids list cannot be empty."

        rows, total_count = preview_concept_set_core(
            concept_ids, include_descendants, limit,
        )

        # Mark is_descendant as bool for staging
        for r in rows:
            r["is_descendant"] = bool(r.get("is_descendant", 0))

        params = dict(
            concept_ids=concept_ids,
            include_descendants=include_descendants,
            limit=limit,
        )
        result_id = stage_concepts("preview_concept_set", params, rows)

        desc_str = " (with descendants)" if include_descendants else " (exact IDs only)"

        lines = [
            f"## Concept Set Preview{desc_str}",
            f"Total resolved concepts: {total_count}",
            "",
        ]

        if not rows:
            lines.append("No valid concepts found for the given IDs.")
            lines.append(result_id_line(result_id))
            return "\n".join(lines)

        lines.append(f"**{len(rows)} concepts** (result_id: {result_id})")
        lines.append("")
        lines.append(
            "| # | concept_name | domain | vocab | class | "
            "std | source |"
        )
        lines.append(
            "|---|:-------------|:-------|:------|:------|"
            ":----|:-------|"
        )
        for idx, r in enumerate(rows):
            source = "input" if not r["is_descendant"] else "descendant"
            std = r.get("standard_concept") or ""
            lines.append(
                f"| {idx} | {r['concept_name'][:50]} | "
                f"{r['domain_id']} | {r['vocabulary_id']} | "
                f"{r['concept_class_id']} | {std} | {source} |"
            )

        if total_count > limit:
            lines.append(
                f"\n*Showing {len(rows)} of {total_count} total concepts. "
                f"Increase limit to see more.*"
            )

        lines.append(result_id_line(result_id))
        return "\n".join(lines)
