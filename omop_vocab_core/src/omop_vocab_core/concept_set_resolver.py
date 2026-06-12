"""Compound concept set resolution: text → search → descendants → preview."""

from __future__ import annotations

from .search import search_concepts_core
from .concept_set import preview_concept_set_core


def resolve_concept_set_core(
    keyword: str,
    domain: str | None = None,
    vocabulary_id: str | None = None,
    include_descendants: bool = True,
    include_synonyms: bool = True,
    standard_only: bool = True,
    max_input_concepts: int = 5,
    preview_limit: int = 50,
) -> dict:
    """Search for concepts by keyword, then resolve as a concept set with descendants.

    Single-call replacement for the search → get_descendants → preview_concept_set
    workflow.

    Returns a dict with:
    - keyword: the search term used
    - input_concepts: list of concepts matched by search (the "seed" concepts)
    - resolved_set: list of all concepts in the set (inputs + descendants)
    - total_count: total number of concepts (may exceed preview_limit)
    - include_descendants: whether descendants were included
    """
    # Step 1: Search for matching concepts
    candidates = search_concepts_core(
        keyword=keyword,
        domain=domain,
        vocabulary_id=vocabulary_id,
        standard_only=standard_only,
        valid_only=True,
        include_synonyms=include_synonyms,
        limit=max_input_concepts,
    )

    if not candidates:
        return {
            "keyword": keyword,
            "input_concepts": [],
            "resolved_set": [],
            "total_count": 0,
            "include_descendants": include_descendants,
            "error": f"No concepts found matching '{keyword}'",
        }

    # Step 2: Resolve concept set with optional descendant expansion
    concept_ids = [c["concept_id"] for c in candidates]
    resolved, total_count = preview_concept_set_core(
        concept_ids=concept_ids,
        include_descendants=include_descendants,
        limit=preview_limit,
    )

    return {
        "keyword": keyword,
        "input_concepts": candidates,
        "resolved_set": resolved,
        "total_count": total_count,
        "include_descendants": include_descendants,
    }
