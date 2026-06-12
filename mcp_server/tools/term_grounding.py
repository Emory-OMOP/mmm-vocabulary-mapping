"""Term grounding tool: constraint-aware concept resolution."""

from mcp.server.fastmcp import FastMCP

from omop_vocab_core.graph_cache import graph_context
from omop_vocab_core.term_grounding import ground_term
from tools._staging_mixin import stage_concepts, result_id_line


def _format_grounded(results: list[dict], text: str, result_id: int | None) -> str:
    """Format grounded concepts as markdown without concept_ids."""
    lines = [f"## Grounding: \"{text}\"", ""]

    if not results:
        lines.append("No matching concepts found.")
        lines.append(result_id_line(result_id))
        return "\n".join(lines)

    lines.append(f"**{len(results)} candidates** (result_id: {result_id})")
    lines.append("")
    lines.append("| # | concept_name | domain | vocab | class | std | tier | score |")
    lines.append("|---|:-------------|:-------|:------|:------|:----|:-----|:------|")
    for idx, r in enumerate(results):
        std = r.get("standard_concept") or ""
        tier = r.get("match_tier", "")
        score = r.get("relevance_score", "")
        if isinstance(score, float):
            score = f"{score:.3f}"
        lines.append(
            f"| {idx} | {str(r.get('concept_name', ''))[:50]} | "
            f"{r.get('domain_id', '')} | {r.get('vocabulary_id', '')} | "
            f"{r.get('concept_class_id', '')} | {std} | {tier} | {score} |"
        )

    lines.append(result_id_line(result_id))
    return "\n".join(lines)


def register_grounding_tools(mcp: FastMCP):

    @mcp.tool()
    async def ground_clinical_term(
        text: str,
        parent_concept_id: int | None = None,
        domain: str | None = None,
        vocabulary_id: str | None = None,
        require_standard: bool = True,
        max_results: int = 5,
    ) -> str:
        """Resolve a free-text clinical term to OMOP concepts with optional hierarchy constraints.

        Like search_concepts but with hierarchy-aware filtering: when parent_concept_id
        is provided, only returns concepts that are descendants of that parent in the
        OMOP hierarchy. This is useful for phenotype construction where you need concepts
        within a specific branch (e.g., all conditions under "Endocrine disorder").

        Returns candidates ranked by hybrid relevance (string similarity + token overlap).

        IMPORTANT — Lay term handling:
        If the user provides a lay or informal term, first normalize it to standard
        clinical terminology, then search with the normalized term. ALWAYS tell the
        user what interpretation you made — e.g., "Interpreting 'the shaking disease'
        as Parkinson disease." This lets the user correct wrong interpretations.

        Search with the lay term as a fallback if the normalized term returns no results.

        Examples of normalization (do this BEFORE calling the tool):
        - "heart attack" → "myocardial infarction"
        - "sugar diabetes" → "diabetes mellitus"
        - "the shaking disease" → "Parkinson disease"
        - "water pill" → "diuretic"
        - "blood thinner" → "anticoagulant"

        Results include a match_tier field indicating how each concept was found:
        - "name": direct concept name match (highest confidence)
        - "synonym": matched via CONCEPT_SYNONYM table (high confidence)
        - "embedding": matched via semantic similarity (lower confidence — verify with user)

        Args:
            text: Clinical term to search for. Use standard medical terminology
                  when possible (e.g., "myocardial infarction" not "heart attack")
            parent_concept_id: If set, only return concepts that are descendants
                              of this concept_id in the hierarchy
            domain: Filter by domain (e.g., "Condition", "Drug", "Measurement")
            vocabulary_id: Filter by vocabulary (e.g., "SNOMED", "RxNorm", "LOINC")
            require_standard: Only return Standard concepts (default: True)
            max_results: Maximum candidates to return (1-20, default 5)
        """
        max_results = min(max(1, max_results), 20)

        with graph_context() as ctx:
            results = ground_term(
                ctx,
                text,
                parent_concept_id=parent_concept_id,
                domain=domain,
                vocabulary_id=vocabulary_id,
                require_standard=require_standard,
                max_results=max_results,
            )

        params = dict(
            text=text, parent_concept_id=parent_concept_id,
            domain=domain, vocabulary_id=vocabulary_id,
            require_standard=require_standard, max_results=max_results,
        )
        result_id = stage_concepts("ground_clinical_term", params, results)

        return _format_grounded(results, text, result_id)
