"""Phenotype simplifier tool: find common ancestors covering a concept set."""

from mcp.server.fastmcp import FastMCP

from omop_vocab_core.phenotype_simplifier import find_common_parents, greedy_parent_cover, validate_seeds


def _format_results(seed_ids, candidates, selected, validation=None) -> str:
    lines = [
        f"## Common Ancestor Analysis",
        f"",
    ]

    # Show seed validation warnings first
    if validation and validation.get("warnings"):
        lines.append("### Seed Validation Warnings")
        for w in validation["warnings"]:
            lines.append(f"- **WARNING:** {w}")
        lines.append("")

        # Show non-standard seed details
        non_std = validation.get("non_standard_seeds", [])
        if non_std:
            lines.append("| Seed ID | Seed Name | Maps to | Standard Target |")
            lines.append("|:--------|:----------|:--------|:----------------|")
            for ns in non_std:
                s = ns["seed"]
                m = ns.get("maps_to")
                if m:
                    lines.append(
                        f"| {s['concept_id']} | {str(s['concept_name'])[:35]} | → {m['concept_id']} | "
                        f"{str(m['concept_name'])[:35]} ({m['vocabulary_id']}) |"
                    )
                else:
                    lines.append(f"| {s['concept_id']} | {str(s['concept_name'])[:35]} | — | No mapping |")
            lines.append("")

    lines.append(f"*{len(seed_ids)} seed concepts → {len(candidates)} candidate parents → {len(selected)} selected*")
    lines.append("")

    if selected:
        lines.append("### Recommended Parent Set")
        lines.append("| concept_id | concept_name | coverage | purity | pollution | newly_covered |")
        lines.append("|:-----------|:-------------|:---------|:-------|:---------|:--------------|")
        for s in selected:
            nc = len(s.get("newly_covered", []))
            lines.append(
                f"| {s['concept_id']} | {str(s['concept_name'])[:45]} | "
                f"{s['coverage']}/{len(seed_ids)} ({s['completeness']:.0%}) | "
                f"{s['purity']:.0%} | {s['pollution']:,} | {nc} new |"
            )

        total_covered = set()
        for s in selected:
            total_covered.update(s.get("newly_covered", []))
        uncovered = set(seed_ids) - total_covered
        if uncovered:
            lines.append(f"\n*{len(uncovered)} seed(s) not covered: {sorted(uncovered)}*")
        else:
            lines.append(f"\n*All {len(seed_ids)} seeds covered.*")

    lines.append("")
    lines.append("### All Candidate Parents (top 20)")
    lines.append("| concept_id | concept_name | coverage | purity | pollution | depth |")
    lines.append("|:-----------|:-------------|:---------|:-------|:---------|:------|")
    for c in candidates[:20]:
        lines.append(
            f"| {c['concept_id']} | {str(c['concept_name'])[:45]} | "
            f"{c['coverage']}/{len(seed_ids)} | {c['purity']:.0%} | "
            f"{c['pollution']:,} | {c['max_depth']} |"
        )

    if len(candidates) > 20:
        lines.append(f"\n*Showing 20 of {len(candidates)} candidates.*")

    return "\n".join(lines)


def register_phenotype_simplifier_tools(mcp: FastMCP):

    @mcp.tool()
    async def find_common_ancestor(
        concept_ids: str,
        max_depth: int = 5,
        min_coverage: int = 2,
        target_coverage: float = 1.0,
    ) -> str:
        """Find the minimum set of parent concepts that covers a group of seed concepts.

        Given a list of specific concepts (e.g., 20 diabetes subtypes), identifies
        parent concepts in the hierarchy that subsume them. Then selects the smallest
        set of parents that covers all seeds, balancing coverage against pollution
        (irrelevant descendants that would be included).

        This is the algorithmic equivalent of what phenotype authors do manually in
        ATLAS: choosing parent concepts for descendant-inclusive concept sets.

        Use this when you have a list of specific concepts and need to find the
        right level of generality for a concept set definition.

        Args:
            concept_ids: Comma-separated OMOP concept_ids (the seed concepts)
            max_depth: Maximum hierarchy levels to search upward (1-10, default 5)
            min_coverage: Minimum seeds a parent must cover to be considered (default 2)
            target_coverage: Fraction of seeds to cover (0.0-1.0, default 1.0 = all)
        """
        seeds = [int(s.strip()) for s in concept_ids.split(",") if s.strip().isdigit()]
        if len(seeds) < 2:
            return "Error: provide at least 2 concept_ids."

        max_depth = min(max(1, max_depth), 10)
        min_coverage = max(1, min_coverage)
        target_coverage = min(max(0.0, target_coverage), 1.0)

        # Validate seeds: check standard status, trace non-standard mappings
        validation = validate_seeds(seeds)

        candidates = find_common_parents(
            seeds,
            max_up_depth=max_depth,
            min_coverage=min_coverage,
        )

        selected = greedy_parent_cover(
            seeds,
            candidates,
            target_coverage=target_coverage,
        )

        return _format_results(seeds, candidates, selected, validation)
