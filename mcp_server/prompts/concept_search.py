"""MCP Prompts for concept search workflows."""

from mcp.server.fastmcp import FastMCP


def register_prompts(mcp: FastMCP):

    @mcp.prompt()
    async def concept_lookup_workflow(clinical_term: str) -> str:
        """Guided workflow for finding the correct OMOP standard concept for a clinical term.

        Args:
            clinical_term: The clinical term to look up (e.g., 'Type 2 Diabetes', 'Metformin')
        """
        return f"""You are looking up the OMOP standard concept for: "{clinical_term}"

Follow this workflow:

1. **Determine the domain**: Is this a Condition, Drug, Procedure, Measurement, or other domain?

2. **Search broadly first**:
   Call `search_concepts` with keyword="{clinical_term}" and the appropriate domain filter.
   Keep standard_only=True (default) to get standard concepts.

3. **Review results carefully**:
   - Check that the concept_name matches your clinical intent
   - Verify the domain_id is correct
   - Note the vocabulary_id (SNOMED for conditions/procedures, RxNorm for drugs, LOINC for measurements)
   - Confirm standard_concept = 'S'

4. **If no standard concept found**:
   - Try standard_only=False to find non-standard/source concepts
   - Then use `get_concept_relationships` with relationship_id='Maps to' to find the standard mapping

5. **If too many results**:
   - Add a vocabulary_id filter (e.g., 'SNOMED' for conditions)
   - Add a concept_class filter (e.g., 'Clinical Finding' for conditions, 'Ingredient' for drugs)

6. **Verify with hierarchy** (optional):
   - Use `get_concept_ancestors` to confirm the concept is at the right level of specificity
   - Use `get_concept_descendants` to see what more specific concepts exist below

7. **Report the result**: Always provide the concept_id, concept_name, domain, vocabulary, and concept_code.
   NEVER guess a concept_id -- always use values returned by the tools.
"""

    @mcp.prompt()
    async def cohort_analysis_workflow(condition: str) -> str:
        """Guided workflow for building and analyzing a patient cohort from a clinical condition.

        Args:
            condition: The clinical condition to build a cohort for (e.g., 'Type 2 Diabetes')
        """
        return f"""You are building a patient cohort for: "{condition}"

Follow this multi-step workflow across available tools:

1. **Find the concept** (vocabulary tools):
   Call `search_concepts` with keyword="{condition}" and domain="Condition".
   Identify the standard SNOMED concept_id. If unsure, check
   `get_concept_relationships` with relationship_id='Maps to'.

2. **Explore the hierarchy** (vocabulary tools):
   Use `get_concept_descendants` to see what specific subtypes exist.
   Decide whether to include descendants in your concept set.

3. **Preview the concept set** (vocabulary tools):
   Call `preview_concept_set` with your chosen concept_ids and
   include_descendants=True to see exactly which concepts will be captured.

4. **Build the cohort definition**:
   Construct a CIRCE cohort definition JSON using the concept_ids.
   Refer to the circe://schema/cohort-definition resource for the format.

5. **Validate and preview** (cohort compiler tools, if available):
   - Call `validate_cohort_definition` to check for errors
   - Call `cohort_dry_run` to preview tables scanned and complexity

6. **Compile to SQL** (cohort compiler tools, if available):
   Call `compile_cohort_definition` with dialect matching your database.

7. **Execute and analyze** (SQL execution tools, if available):
   Run the compiled SQL to create the cohort, then query the results
   for patient counts, demographics, and characteristics.

Each step may use tools from different servers. Not all servers may be
connected — skip steps for tools that aren't available.
"""
