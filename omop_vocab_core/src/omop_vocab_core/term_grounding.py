"""Constraint-based term grounding with resolver cascade.

Resolution tiers (in order):
1. ILIKE on concept_name — highest confidence, exact/substring match
2. ILIKE on concept_synonym — catches curated lay-to-clinical mappings
3. SapBERT embedding search — semantic fallback for unmatched queries

Applies hybrid re-ranking blending string distance and token overlap
(per BioNNE-L 2025 hybrid re-ranking pattern) across all tiers.
"""

from __future__ import annotations

import logging
from difflib import SequenceMatcher

from .graph_cache import GraphContext
from .search import search_concepts_core
from . import embedding_search

logger = logging.getLogger(__name__)

# Minimum number of ILIKE results before falling through to next tier
MIN_ILIKE_RESULTS = 3


def _levenshtein_ratio(a: str, b: str) -> float:
    """Levenshtein similarity ratio via SequenceMatcher (0-1, higher = more similar)."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _jaccard_tokens(a: str, b: str) -> float:
    """Token-level Jaccard similarity (0-1)."""
    tokens_a = set(a.lower().split())
    tokens_b = set(b.lower().split())
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def _hybrid_score(
    query: str,
    concept_name: str,
    *,
    w_levenshtein: float = 0.4,
    w_jaccard: float = 0.4,
    w_name_length: float = 0.2,
) -> float:
    """Compute hybrid lexical relevance score for a candidate concept.

    Blends Levenshtein similarity, token Jaccard, and a brevity bonus
    (shorter names = more specific = usually better matches).
    Weights derived from BioNNE-L 2025 hybrid re-ranking pattern.
    """
    lev = _levenshtein_ratio(query, concept_name)
    jac = _jaccard_tokens(query, concept_name)
    # Brevity bonus: favor shorter, more specific concept names
    brevity = 1.0 / (1.0 + len(concept_name) / 100.0)
    return w_levenshtein * lev + w_jaccard * jac + w_name_length * brevity


def ground_term(
    ctx: GraphContext,
    text: str,
    *,
    parent_concept_id: int | None = None,
    domain: str | None = None,
    vocabulary_id: str | None = None,
    require_standard: bool = True,
    max_results: int = 5,
) -> list[dict]:
    """Find OMOP concepts matching text, optionally constrained by hierarchy.

    Parameters
    ----------
    ctx : GraphContext
        Graph context with DuckDB connection and caches.
    text : str
        Free-text clinical term to search for.
    parent_concept_id : int, optional
        If provided, only return candidates that are descendants of this concept.
    domain : str, optional
        Filter candidates by domain (e.g., "Condition", "Drug").
    vocabulary_id : str, optional
        Filter candidates by vocabulary (e.g., "SNOMED", "RxNorm").
    require_standard : bool
        Only return standard concepts (default True).
    max_results : int
        Maximum candidates to return (default 5).

    Returns
    -------
    list of dict
        Each dict contains concept metadata plus optional path_to_parent info.
    """
    # Resolver cascade: ILIKE name → ILIKE synonym → embedding search
    search_limit = max(max_results * 4, 20)
    seen_ids: set[int] = set()
    candidates: list[dict] = []

    # Tier 1: ILIKE on concept_name
    tier1 = search_concepts_core(
        keyword=text, domain=domain, vocabulary_id=vocabulary_id,
        standard_only=require_standard, valid_only=True,
        include_synonyms=False, limit=min(search_limit, 50),
    )
    for c in tier1:
        if c["concept_id"] not in seen_ids:
            c["match_tier"] = "name"
            candidates.append(c)
            seen_ids.add(c["concept_id"])

    # Tier 2: ILIKE on concept_synonym (if tier 1 insufficient)
    if len(candidates) < MIN_ILIKE_RESULTS:
        tier2 = search_concepts_core(
            keyword=text, domain=domain, vocabulary_id=vocabulary_id,
            standard_only=require_standard, valid_only=True,
            include_synonyms=True, limit=min(search_limit, 50),
        )
        for c in tier2:
            if c["concept_id"] not in seen_ids:
                c["match_tier"] = "synonym"
                candidates.append(c)
                seen_ids.add(c["concept_id"])

    # Tier 3: Embedding search (if still insufficient)
    if len(candidates) < MIN_ILIKE_RESULTS and embedding_search.is_available():
        logger.debug("Falling through to embedding search for '%s'", text)
        tier3 = embedding_search.search_embeddings(
            text=text, domain=domain, vocabulary_id=vocabulary_id,
            standard_only=require_standard, limit=min(search_limit, 20),
        )
        for c in tier3:
            if c["concept_id"] not in seen_ids:
                c["match_tier"] = "embedding"
                c["standard_concept"] = "S"  # embedding DB only contains standard concepts
                c["invalid_reason"] = None
                candidates.append(c)
                seen_ids.add(c["concept_id"])

    # Apply hybrid re-ranking to all candidates
    for candidate in candidates:
        candidate["relevance_score"] = _hybrid_score(text, candidate.get("concept_name", ""))

    if not parent_concept_id:
        candidates.sort(key=lambda c: -c["relevance_score"])
        return candidates[:max_results]

    # Validate ancestry: check each candidate is a descendant of parent
    parent_view = ctx.concept_view(parent_concept_id)
    parent_name = parent_view.get("concept_name", f"Unknown ({parent_concept_id})") if parent_view else f"Unknown ({parent_concept_id})"

    results = []
    for candidate in candidates:
        cid = candidate["concept_id"]
        if cid == parent_concept_id:
            candidate["path_to_parent"] = "Is the parent concept itself"
            candidate["separation"] = 0
            results.append(candidate)
            continue

        separation = ctx.is_ancestor(parent_concept_id, cid)
        if separation is not None:
            candidate["path_to_parent"] = (
                f"Descendant of {parent_name} ({parent_concept_id}) "
                f"at {separation} level(s) of separation"
            )
            candidate["separation"] = separation
            results.append(candidate)

        if len(results) >= max_results:
            break

    # Sort by separation (closer = better), then by hybrid relevance score
    results.sort(key=lambda r: (r.get("separation", 999), -r.get("relevance_score", 0)))
    return results[:max_results]
