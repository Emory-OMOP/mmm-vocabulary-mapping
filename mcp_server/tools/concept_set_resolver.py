"""Concept set resolver tool: text in, concept set preview out."""

from mcp.server.fastmcp import FastMCP

from omop_vocab_core.concept_set_resolver import resolve_concept_set_core
from tools._staging_mixin import stage_concepts, result_id_line


def _format_resolved_set(result: dict, result_id: int | None) -> str:
    """Format the resolved concept set as markdown without concept_ids."""
    lines = [f"## Concept Set: \"{result['keyword']}\"", ""]

    inputs = result.get("input_concepts", [])
    if not inputs:
        lines.append(result.get("error", "No concepts found."))
        lines.append(result_id_line(result_id))
        return "\n".join(lines)

    lines.append(f"### Seed Concepts ({len(inputs)})")
    lines.append("| # | concept_name | domain | vocab | class |")
    lines.append("|---|:-------------|:-------|:------|:------|")
    for idx, c in enumerate(inputs):
        lines.append(
            f"| {idx} | {str(c['concept_name'])[:50]} | "
            f"{c['domain_id']} | {c['vocabulary_id']} | {c['concept_class_id']} |"
        )

    resolved = result.get("resolved_set", [])
    total = result.get("total_count", 0)
    desc = result.get("include_descendants", False)

    lines.append("")
    if desc:
        lines.append(f"### Resolved Set ({total:,} total, showing {len(resolved)})")
    else:
        lines.append(f"### Resolved Set ({len(resolved)} concepts, no descendants)")

    lines.append("| # | concept_name | domain | vocab | source |")
    lines.append("|---|:-------------|:-------|:------|:-------|")
    for idx, r in enumerate(resolved):
        source = "descendant" if r.get("is_descendant") else "input"
        lines.append(
            f"| {idx} | {str(r['concept_name'])[:50]} | "
            f"{r['domain_id']} | {r['vocabulary_id']} | {source} |"
        )

    if total > len(resolved):
        lines.append(f"\n*Showing {len(resolved)} of {total:,} total concepts. Use preview_concept_set for full results.*")

    lines.append(result_id_line(result_id))
    return "\n".join(lines)


def register_concept_set_resolver_tools(mcp: FastMCP):

    @mcp.tool()
    async def resolve_concept_set(
        keyword: str,
        domain: str | None = None,
        vocabulary_id: str | None = None,
        include_descendants: bool = True,
        max_seed_concepts: int = 5,
        preview_limit: int = 50,
    ) -> str:
        """Build a concept set from a search term in one call.

        Searches for OMOP concepts matching the keyword (including synonyms),
        then expands with all descendant concepts to produce a full concept set
        preview. This replaces the manual workflow of calling search_concepts,
        then get_concept_descendants, then preview_concept_set.

        Use this when a researcher says "I want a concept set for diabetes" or
        "build me a set for ACE inhibitors" — it handles the full pipeline.

        Args:
            keyword: Clinical term to search for (e.g., "type 2 diabetes", "ACE inhibitor")
            domain: Filter by domain (e.g., "Condition", "Drug", "Measurement")
            vocabulary_id: Filter by vocabulary (e.g., "SNOMED", "RxNorm")
            include_descendants: Include descendant concepts via hierarchy (default: True)
            max_seed_concepts: Maximum seed concepts from search (1-10, default: 5)
            preview_limit: Maximum concepts in preview (1-200, default: 50)
        """
        max_seed_concepts = min(max(1, max_seed_concepts), 10)
        preview_limit = min(max(1, preview_limit), 200)

        result = resolve_concept_set_core(
            keyword=keyword,
            domain=domain,
            vocabulary_id=vocabulary_id,
            include_descendants=include_descendants,
            max_input_concepts=max_seed_concepts,
            preview_limit=preview_limit,
        )

        # Stage the resolved set (includes both seed and descendant concepts)
        resolved = result.get("resolved_set", [])
        for r in resolved:
            r["is_descendant"] = bool(r.get("is_descendant", False))

        params = dict(
            keyword=keyword, domain=domain, vocabulary_id=vocabulary_id,
            include_descendants=include_descendants,
            max_seed_concepts=max_seed_concepts, preview_limit=preview_limit,
        )
        result_id = stage_concepts("resolve_concept_set", params, resolved)

        return _format_resolved_set(result, result_id)
