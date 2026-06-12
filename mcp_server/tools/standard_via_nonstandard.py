"""standard_via_nonstandard tool: two-step resolution — embedding match on
non-standard concepts + Maps-to → Standard target.

This tool complements search_concepts/ground_clinical_term (both of which
search Standard concepts directly). Use it when:
  - Source text closely matches a NON-STANDARD vocabulary name (e.g., an
    ICD10CM or CPT4 entry) more than it matches any Standard concept name.
  - You want to leverage OHDSI's community-curated Maps-to mappings as
    the bridge to the Standard target, rather than relying on embedding
    similarity directly into the Standard vocabulary.

Concept IDs are staged server-side. The LLM sees only concept names,
similarity scores, and a result_id for later reference.
"""

from mcp.server.fastmcp import FastMCP

from omop_vocab_core.nonstandard_resolver import (
    resolve_standard_via_nonstandard,
    is_available,
)
from tools._staging_mixin import stage_concepts, result_id_line


def _format_results(
    results: list[dict],
    text: str,
    result_id: int | None,
) -> str:
    lines = [f'## Standard via non-standard: "{text}"', ""]

    if not results:
        if not is_available():
            lines.append(
                "Non-standard embeddings DB not available. "
                "Falling back to direct standard search is recommended."
            )
        else:
            lines.append("No Standard concepts reached via non-standard embedding + Maps-to.")
        lines.append(result_id_line(result_id))
        return "\n".join(lines)

    lines.append(f"**{len(results)} Standard concepts** (result_id: {result_id})")
    lines.append("")
    lines.append("| # | standard_name | vocab | domain | class | sim | n_paths |")
    lines.append("|---|:--------------|:------|:-------|:------|:----|:--------|")
    for idx, r in enumerate(results):
        lines.append(
            f"| {idx} | {str(r['standard_concept_name'])[:50]} | "
            f"{r['standard_vocabulary_id']} | {r['standard_domain_id']} | "
            f"{r['standard_concept_class_id']} | "
            f"{r['max_similarity']:.3f} | {r['n_source_paths']} |"
        )

    # Source-path provenance table (compact, up to 3 paths per standard)
    lines.append("")
    lines.append("### Source paths (top 3 per target)")
    lines.append("")
    lines.append("| # | via_source_name | via_vocab | sim |")
    lines.append("|---|:----------------|:----------|:----|")
    for idx, r in enumerate(results):
        for path in r["source_paths"][:3]:
            lines.append(
                f"| {idx} | {str(path['concept_name'])[:50]} | "
                f"{path['vocabulary_id']} | {path['similarity']:.3f} |"
            )

    lines.append(result_id_line(result_id))
    return "\n".join(lines)


def register_standard_via_nonstandard(mcp: FastMCP):

    @mcp.tool()
    async def standard_via_nonstandard(
        text: str,
        top_k_nonstandard: int = 20,
        top_k_standard: int = 10,
        target_domain: str | None = None,
        target_vocabulary_id: str | None = None,
    ) -> str:
        """Resolve source text to Standard concepts via a two-step path:
        source text → non-standard embedding match → Maps-to → Standard target.

        When to use this tool (vs. search_concepts or ground_clinical_term):

        - The source text is in the style of a source vocabulary (ICD10CM,
          CPT4, HCPCS, institutional codes) rather than canonical SNOMED
          phrasing. Example: "Acute myocardial infarction, unspecified" is
          the ICD10CM phrasing, likely to embedding-match an ICD10CM name
          better than the SNOMED standard name "Myocardial infarction".
        - You want the bridge to Standard to be the community's manually
          curated Maps-to relationship rather than pure embedding similarity.
        - You're doing cross-vocabulary mapping (e.g., OHDSI MindMeetsMachines-
          style challenges) where many source strings are verbatim from
          source vocabularies.

        How it works:
        1. Encodes the query text with SapBERT and retrieves the top-K
           non-standard OMOP concepts by cosine similarity.
        2. For each non-standard candidate, follows CONCEPT_RELATIONSHIP where
           relationship_id='Maps to' (active, non-deprecated) to obtain the
           Standard target concept_ids.
        3. Groups the results by Standard concept, keeping max similarity
           across contributing non-standard paths.
        4. Returns Standard concepts with a provenance trail showing which
           non-standard (and similarity score) led to each target.

        Output is ordered by the best similarity from any contributing
        non-standard path. Concept IDs are staged server-side; only names,
        scores, and a result_id are returned.

        Args:
            text: Source text to resolve.
            top_k_nonstandard: Non-standard candidates to consider from
                embedding search. Higher values broaden coverage at the cost
                of more Maps-to joins. Default 20.
            top_k_standard: Maximum Standard concepts to return. Default 10.
            target_domain: Optional filter on the Standard target's domain
                (e.g., 'Procedure', 'Measurement', 'Condition', 'Drug').
            target_vocabulary_id: Optional filter on the Standard target's
                vocabulary_id (e.g., 'SNOMED', 'LOINC', 'RxNorm').
        """
        top_k_nonstandard = min(max(1, top_k_nonstandard), 100)
        top_k_standard = min(max(1, top_k_standard), 50)

        results = resolve_standard_via_nonstandard(
            text=text,
            top_k_nonstandard=top_k_nonstandard,
            top_k_standard=top_k_standard,
            target_domain=target_domain,
            target_vocabulary_id=target_vocabulary_id,
        )

        # Stage the Standard concepts (concept_ids stay server-side)
        staged = [
            {
                "concept_id": r["standard_concept_id"],
                "concept_name": r["standard_concept_name"],
                "vocabulary_id": r["standard_vocabulary_id"],
                "domain_id": r["standard_domain_id"],
                "concept_class_id": r["standard_concept_class_id"],
                "standard_concept": "S",
            }
            for r in results
        ]
        params = dict(
            text=text,
            top_k_nonstandard=top_k_nonstandard,
            top_k_standard=top_k_standard,
            target_domain=target_domain,
            target_vocabulary_id=target_vocabulary_id,
        )
        result_id = stage_concepts("standard_via_nonstandard", params, staged)

        return _format_results(results, text, result_id)
