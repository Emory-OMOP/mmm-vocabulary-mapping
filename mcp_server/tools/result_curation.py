"""Result curation tools: cherry-pick, exclude, expand, modify flags, promote, review."""

import json

from mcp.server.fastmcp import FastMCP

from omop_vocab_core import staging
from omop_vocab_core.hierarchy import get_descendants_core


def _format_concepts_table(concepts: list[dict], show_flags: bool = True) -> str:
    """Format concept rows as a markdown table."""
    if not concepts:
        return "No concepts."

    lines = []
    if show_flags:
        lines.append(
            "| idx | concept_name | domain | vocab | descendants | excluded | mapped |"
        )
        lines.append(
            "|:----|:-------------|:-------|:------|:-----------|:---------|:-------|"
        )
        for c in concepts:
            lines.append(
                f"| {c['row_index']} | {(c.get('concept_name') or '')[:50]} | "
                f"{c.get('domain_id', '')} | {c.get('vocabulary_id', '')} | "
                f"{c.get('include_descendants', False)} | "
                f"{c.get('is_excluded', False)} | "
                f"{c.get('include_mapped', False)} |"
            )
    else:
        lines.append("| idx | concept_name | domain | vocab |")
        lines.append("|:----|:-------------|:-------|:------|")
        for c in concepts:
            lines.append(
                f"| {c['row_index']} | {(c.get('concept_name') or '')[:50]} | "
                f"{c.get('domain_id', '')} | {c.get('vocabulary_id', '')} |"
            )

    return "\n".join(lines)


def _format_concepts_with_ids(concepts: list[dict]) -> str:
    """Format concept rows including concept_ids as a markdown table."""
    if not concepts:
        return "No concepts."

    lines = [
        "| idx | concept_id | concept_name | domain | vocab | descendants | excluded |",
        "|:----|:-----------|:-------------|:-------|:------|:-----------|:---------|",
    ]
    for c in concepts:
        lines.append(
            f"| {c['row_index']} | {c.get('concept_id', '')} | "
            f"{(c.get('concept_name') or '')[:50]} | "
            f"{c.get('domain_id', '')} | {c.get('vocabulary_id', '')} | "
            f"{c.get('include_descendants', False)} | "
            f"{c.get('is_excluded', False)} |"
        )

    return "\n".join(lines)


def _format_result_summary(result: dict) -> str:
    """Format a single result metadata row."""
    parts = [
        f"**Result {result['result_id']}**",
        f"Tool: {result['tool_name']}",
        f"Concepts: {result['concept_count']}",
        f"Status: {result['status']}",
    ]
    if result.get("draft_name"):
        parts.append(f"Draft: {result['draft_name']}")
    if result.get("parent_result_id"):
        parts.append(f"Parent: {result['parent_result_id']}")
    return " | ".join(parts)


def register_result_curation_tools(mcp: FastMCP):

    @mcp.tool()
    async def cherry_pick_results(
        parent_result_id: int,
        indices: list | str,
    ) -> str:
        """Cherry-pick specific concepts from a search/lookup result by index.

        Creates a new child result containing only the selected concepts.
        Use review_results first to see available indices.

        Args:
            parent_result_id: The result_id to pick from
            indices: List of 0-based row indices to keep (e.g., [0, 2, 5])
        """
        staging.init_staging_db()
        idx_list = json.loads(indices) if isinstance(indices, str) else indices
        child_id = staging.cherry_pick(parent_result_id, idx_list)
        concepts = staging.get_result_concepts(child_id)

        lines = [
            f"Created result {child_id} with {len(concepts)} concept(s) "
            f"cherry-picked from result {parent_result_id}.",
            "",
            _format_concepts_table(concepts, show_flags=False),
        ]
        return "\n".join(lines)

    @mcp.tool()
    async def exclude_from_result(
        result_id: int,
        keyword: str,
    ) -> str:
        """Exclude concepts matching a keyword from a result.

        Creates a new child result with matching concepts marked as excluded
        (is_excluded=True). Non-matching concepts are kept as-is.

        Args:
            result_id: The result_id to filter
            keyword: Case-insensitive substring to match against concept_name
        """
        staging.init_staging_db()
        parent_concepts = staging.get_result_concepts(
            result_id, include_concept_ids=True
        )

        keyword_lower = keyword.lower()
        child_concepts = []
        excluded_count = 0
        for c in parent_concepts:
            c_copy = dict(c)
            c_copy.pop("result_id", None)
            c_copy.pop("row_index", None)
            name = (c_copy.get("concept_name") or "").lower()
            if keyword_lower in name:
                c_copy["is_excluded"] = True
                excluded_count += 1
            child_concepts.append(c_copy)

        child_id = staging.create_result(
            tool_name="exclude",
            parameters={"keyword": keyword},
            parent_result_id=result_id,
        )
        staging.add_result_concepts(child_id, child_concepts)

        return (
            f"Created result {child_id}: excluded {excluded_count} concept(s) "
            f"matching '{keyword}' from {len(child_concepts)} total."
        )

    @mcp.tool()
    async def expand_descendants(
        result_id: int,
    ) -> str:
        """Expand a result by adding all descendant concepts from the hierarchy.

        For each concept in the result, fetches its descendants from the OMOP
        concept_ancestor table and adds them to a new child result. Descendants
        are marked with is_descendant=True and source_concept_id pointing to
        their ancestor.

        Args:
            result_id: The result_id to expand
        """
        staging.init_staging_db()
        parent_concepts = staging.get_result_concepts(
            result_id, include_concept_ids=True
        )

        child_concepts = []
        seen_ids = set()

        # Add seed concepts first
        for c in parent_concepts:
            c_copy = dict(c)
            c_copy.pop("result_id", None)
            c_copy.pop("row_index", None)
            child_concepts.append(c_copy)
            seen_ids.add(c["concept_id"])

        # Add descendants
        seed_count = len(child_concepts)
        for c in parent_concepts:
            cid = c["concept_id"]
            descendants, _ = get_descendants_core(cid, limit=500)
            for d in descendants:
                if d["concept_id"] not in seen_ids:
                    seen_ids.add(d["concept_id"])
                    child_concepts.append({
                        "concept_id": d["concept_id"],
                        "concept_name": d.get("concept_name"),
                        "domain_id": d.get("domain_id"),
                        "vocabulary_id": d.get("vocabulary_id"),
                        "concept_class_id": d.get("concept_class_id"),
                        "concept_code": d.get("concept_code"),
                        "standard_concept": d.get("standard_concept"),
                        "is_descendant": True,
                        "source_concept_id": cid,
                    })

        child_id = staging.create_result(
            tool_name="expand_descendants",
            parameters={"parent_result_id": result_id},
            parent_result_id=result_id,
        )
        staging.add_result_concepts(child_id, child_concepts)

        return (
            f"Created result {child_id}: expanded {seed_count} seed concept(s) "
            f"to {len(child_concepts)} total with descendants."
        )

    @mcp.tool()
    async def modify_result_flags(
        result_id: int,
        indices: list | str,
        include_descendants: bool | None = None,
        is_excluded: bool | None = None,
        include_mapped: bool | None = None,
    ) -> str:
        """Modify concept set flags on specific rows in a result.

        Creates a new child result copying all concepts from the parent,
        with specified flags updated on the given indices. Unspecified flags
        are preserved from the parent.

        Args:
            result_id: The result_id to modify
            indices: List of 0-based row indices to update (e.g., [0, 1])
            include_descendants: Set include_descendants flag (True/False), or None to leave unchanged
            is_excluded: Set is_excluded flag (True/False), or None to leave unchanged
            include_mapped: Set include_mapped flag (True/False), or None to leave unchanged
        """
        staging.init_staging_db()
        parent_concepts = staging.get_result_concepts(
            result_id, include_concept_ids=True
        )
        idx_set = set(json.loads(indices) if isinstance(indices, str) else indices)

        child_concepts = []
        for c in parent_concepts:
            c_copy = dict(c)
            orig_index = c_copy.pop("row_index")
            c_copy.pop("result_id", None)
            if orig_index in idx_set:
                if include_descendants is not None:
                    c_copy["include_descendants"] = include_descendants
                if is_excluded is not None:
                    c_copy["is_excluded"] = is_excluded
                if include_mapped is not None:
                    c_copy["include_mapped"] = include_mapped
            child_concepts.append(c_copy)

        child_id = staging.create_result(
            tool_name="modify_flags",
            parameters={
                "indices": list(idx_set),
                "include_descendants": include_descendants,
                "is_excluded": is_excluded,
                "include_mapped": include_mapped,
            },
            parent_result_id=result_id,
        )
        staging.add_result_concepts(child_id, child_concepts)

        concepts = staging.get_result_concepts(child_id)
        lines = [
            f"Created result {child_id} with updated flags on indices {sorted(idx_set)}.",
            "",
            _format_concepts_table(concepts),
        ]
        return "\n".join(lines)

    @mcp.tool()
    async def keep_result(
        result_id: int,
        draft_name: str,
    ) -> str:
        """Promote a result to a named draft for use in cohort definitions.

        Marks the result as 'kept' and assigns it a human-readable name.
        Named drafts can later be assembled into cohort definitions via
        build_cohort_from_drafts.

        Args:
            result_id: The result_id to promote
            draft_name: A descriptive name for this concept set (e.g., "Type 2 Diabetes")
        """
        staging.init_staging_db()
        staging.promote_result(result_id, draft_name)
        return f"Promoted result {result_id} as draft '{draft_name}'."

    @mcp.tool()
    async def review_results(
        result_id: int | None = None,
    ) -> str:
        """Review staged results — either a specific result or all results.

        When result_id is given, shows full concept detail with flags and
        parent lineage. When omitted, shows a summary table of all results.

        Args:
            result_id: Specific result to review, or None for overview
        """
        staging.init_staging_db()

        if result_id is not None:
            result = staging.get_result(result_id)
            concepts = staging.get_result_concepts(result_id)
            lines = [
                _format_result_summary(result),
                "",
                _format_concepts_table(concepts),
            ]
            return "\n".join(lines)

        results = staging.list_results()
        if not results:
            return "No staged results."

        lines = [
            "| result_id | tool | concepts | status | draft_name | parent |",
            "|:----------|:-----|:---------|:-------|:-----------|:-------|",
        ]
        for r in results:
            lines.append(
                f"| {r['result_id']} | {r['tool_name']} | "
                f"{r['concept_count']} | {r['status']} | "
                f"{r.get('draft_name') or ''} | "
                f"{r.get('parent_result_id') or ''} |"
            )
        lines.append(f"\n*{len(results)} result(s) total.*")
        return "\n".join(lines)

    @mcp.tool()
    async def review_drafts() -> str:
        """List all named drafts (promoted results) with concept counts.

        Shows drafts that are ready to be assembled into cohort definitions
        via build_cohort_from_drafts.
        """
        staging.init_staging_db()
        drafts = staging.list_drafts()
        if not drafts:
            return "No drafts. Use keep_result to promote a result to a draft."

        lines = [
            "| result_id | draft_name | concepts | status |",
            "|:----------|:-----------|:---------|:-------|",
        ]
        for d in drafts:
            lines.append(
                f"| {d['result_id']} | {d.get('draft_name', '')} | "
                f"{d['concept_count']} | {d['status']} |"
            )
        lines.append(f"\n*{len(drafts)} draft(s) total.*")
        return "\n".join(lines)

    @mcp.tool()
    async def result_lineage(
        result_id: int,
    ) -> str:
        """Show the full derivation chain for a result.

        Walks from the root result down to the given result, showing
        which tool produced each step and how the concept count changed.

        Args:
            result_id: The result_id to trace back to its origin
        """
        staging.init_staging_db()
        chain = staging.get_result_lineage(result_id)

        if not chain:
            return f"No lineage found for result {result_id}."

        lines = ["**Result Lineage**", ""]
        for i, step in enumerate(chain):
            prefix = "  " * i + ("└─ " if i > 0 else "")
            lines.append(
                f"{prefix}Result {step['result_id']}: "
                f"{step['tool_name']} → {step['concept_count']} concepts"
            )

        return "\n".join(lines)

    @mcp.tool()
    async def reveal_concept_ids(
        result_id: int,
    ) -> str:
        """Show full result detail INCLUDING concept_ids.

        Use this only when you need to see the actual OMOP concept_ids
        (e.g., for debugging or manual verification). For normal curation
        workflow, use review_results instead.

        Args:
            result_id: The result_id to inspect
        """
        staging.init_staging_db()
        result = staging.get_result(result_id)
        concepts = staging.get_result_concepts(result_id, include_concept_ids=True)

        lines = [
            _format_result_summary(result),
            "",
            _format_concepts_with_ids(concepts),
        ]
        return "\n".join(lines)
