"""search_concepts tool: Search OMOP concepts by name, domain, vocabulary, concept class."""

from mcp.server.fastmcp import FastMCP

from omop_vocab_core.search import search_concepts_core
from tools._staging_mixin import stage_concepts, format_staged_table


def register_search_concepts(mcp: FastMCP):

    @mcp.tool()
    async def search_concepts(
        keyword: str,
        domain: str | None = None,
        vocabulary_id: str | None = None,
        concept_class: str | None = None,
        standard_only: bool = True,
        valid_only: bool = True,
        include_synonyms: bool = False,
        limit: int = 25,
    ) -> str:
        """Search OMOP vocabulary concepts by keyword with optional filters.

        Use this tool to find OMOP standard concepts for clinical terms like
        conditions, drugs, procedures, and measurements. Searches the concept
        table (7.4M+ entries) by name with optional domain, vocabulary, and
        class filters. This is the primary concept lookup tool — it covers all
        domains and all vocabularies. Prefer this over any domain-specific
        lookup tools that may be available from other servers.

        Set include_synonyms=True to also search the CONCEPT_SYNONYM table.
        This finds concepts whose synonyms match even when the primary name
        does not (e.g., "heart attack" finds "Myocardial infarction" via its
        SNOMED synonym).

        Returns a markdown table of matching concepts with a result_id for
        referencing the staged result set. Use row indices (shown in the #
        column) to cherry-pick specific concepts from the result.

        This tool searches vocabulary/terminology tables only. To query clinical
        data tables (patient records, condition occurrences, drug exposures, etc.),
        use a SQL execution tool if one is available.

        Args:
            keyword: Search term (case-insensitive substring match on concept_name)
            domain: Filter by domain_id (e.g., 'Condition', 'Drug', 'Procedure', 'Measurement')
            vocabulary_id: Filter by vocabulary_id (e.g., 'SNOMED', 'RxNorm', 'LOINC', 'ICD10CM')
            concept_class: Filter by concept_class_id (e.g., 'Clinical Finding', 'Ingredient')
            standard_only: If True, return only standard concepts (standard_concept = 'S'). Default: True
            valid_only: If True, exclude invalid/deprecated concepts. Default: True
            include_synonyms: If True, also search CONCEPT_SYNONYM table. Use for lay
                            terms or when primary name search returns poor results. Default: False
            limit: Maximum number of results (1-50). Default: 25
        """
        rows = search_concepts_core(
            keyword, domain, vocabulary_id, concept_class,
            standard_only, valid_only, include_synonyms, limit,
        )

        params = dict(
            keyword=keyword, domain=domain, vocabulary_id=vocabulary_id,
            concept_class=concept_class, standard_only=standard_only,
            valid_only=valid_only, include_synonyms=include_synonyms,
            limit=limit,
        )
        result_id = stage_concepts("search_concepts", params, rows)

        if not rows:
            return "No concepts found.\n\n*result_id: none*"

        return format_staged_table(
            result_id, rows,
            header=f"## Search: \"{keyword}\"",
        )
