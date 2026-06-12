"""MCP Resources for OMOP documentation and vocabulary reference."""

from mcp.server.fastmcp import FastMCP

from db import get_connection, qualified_vocab_table


def register_resources(mcp: FastMCP):

    @mcp.resource("omop://vocabulary/tables")
    async def vocabulary_tables() -> str:
        """OMOP CDM Vocabulary table descriptions and their purposes."""
        return """# OMOP CDM Vocabulary Tables

## concept
The central table. Each row is a unique clinical Concept from a source vocabulary
(SNOMED, RxNorm, LOINC, ICD10CM, etc.). Contains 7.4M+ concepts.
- concept_id: unique integer identifier (use this, never guess)
- concept_name: human-readable name
- domain_id: which clinical domain (Condition, Drug, Procedure, Measurement, etc.)
- vocabulary_id: source vocabulary (SNOMED, RxNorm, LOINC, ICD10CM, etc.)
- concept_class_id: sub-classification within vocabulary
- standard_concept: 'S' = Standard (use in analysis), 'C' = Classification, NULL = non-standard source
- concept_code: code in source vocabulary (e.g., SNOMED code, RxNorm RXCUI)
- invalid_reason: NULL = valid, 'D' = deleted, 'U' = updated/replaced

## concept_ancestor
Precomputed transitive closure of the concept hierarchy. Contains ALL
ancestor-descendant pairs, not just direct parents. Used by get_concept_ancestors
and get_concept_descendants tools.
- ancestor_concept_id, descendant_concept_id: the pair
- min_levels_of_separation: shortest path between them
- max_levels_of_separation: longest path between them

## concept_relationship
Direct relationships between concept pairs. Types include:
- 'Maps to': Non-standard to standard concept mapping
- 'Is a': Direct hierarchical parent
- 'Has ingredient': Drug to ingredient
- 'Has finding site': Condition to anatomy
- 'Mapped from': Reverse of 'Maps to'

## concept_synonym
Alternative names/translations for concepts.

## domain
Reference table of OMOP domains: Condition, Drug, Procedure, Measurement,
Observation, Device, Specimen, etc.

## vocabulary
Reference table of all vocabularies: SNOMED, RxNorm, LOINC, ICD10CM, ICD10PCS,
CPT4, HCPCS, NDC, ATC, MeSH, etc.

## drug_strength
Amount/concentration of active ingredients in drug products.

## relationship
Reference table of all relationship types used in concept_relationship.
"""

    @mcp.resource("omop://vocabulary/domains")
    async def vocabulary_domains() -> str:
        """List all OMOP domains with standard concept counts."""
        with get_connection() as conn:
            results = conn.execute(f"""
                SELECT d.domain_id, d.domain_name,
                       COUNT(c.concept_id) AS concept_count
                FROM {qualified_vocab_table('domain')} d
                LEFT JOIN {qualified_vocab_table('concept')} c
                    ON d.domain_id = c.domain_id
                    AND c.standard_concept = 'S'
                    AND c.invalid_reason IS NULL
                GROUP BY d.domain_id, d.domain_name
                ORDER BY concept_count DESC
            """).fetchall()

        lines = ["# OMOP Domains\n"]
        lines.append("| domain_id | domain_name | standard_concepts |")
        lines.append("|:----------|:------------|:------------------|")
        for domain_id, domain_name, count in results:
            lines.append(f"| {domain_id} | {domain_name} | {count:,} |")
        return "\n".join(lines)

    @mcp.resource("omop://vocabulary/vocabularies")
    async def vocabulary_list() -> str:
        """List all vocabularies with versions and standard concept counts."""
        with get_connection() as conn:
            results = conn.execute(f"""
                SELECT v.vocabulary_id, v.vocabulary_name, v.vocabulary_version,
                       COUNT(c.concept_id) AS concept_count
                FROM {qualified_vocab_table('vocabulary')} v
                LEFT JOIN {qualified_vocab_table('concept')} c
                    ON v.vocabulary_id = c.vocabulary_id
                    AND c.standard_concept = 'S'
                    AND c.invalid_reason IS NULL
                GROUP BY v.vocabulary_id, v.vocabulary_name, v.vocabulary_version
                ORDER BY concept_count DESC
            """).fetchall()

        lines = ["# Available Vocabularies\n"]
        lines.append("| vocabulary_id | vocabulary_name | version | standard_concepts |")
        lines.append("|:--------------|:----------------|:--------|:------------------|")
        for vid, vname, vver, count in results:
            lines.append(f"| {vid} | {vname[:50]} | {vver or 'N/A'} | {count:,} |")
        return "\n".join(lines)

    @mcp.resource("omop://vocabulary/preferred")
    async def preferred_vocabularies() -> str:
        """Preferred vocabulary mappings for clinical domains (best practice)."""
        return """# Preferred OMOP Vocabularies by Domain

When searching for concepts, use these standard vocabularies:

| Domain | Preferred Vocabulary | concept_class_id | Notes |
|:-------|:--------------------|:-----------------|:------|
| Condition | SNOMED | Clinical Finding | ICD10CM maps to SNOMED via 'Maps to'. |
| Drug | RxNorm | Ingredient | NDC maps to RxNorm. Use Ingredient for cohorts. |
| Procedure | SNOMED | Procedure | CPT4/HCPCS map to SNOMED. |
| Measurement | LOINC | Lab Test | Standard labs/vitals. |
| Observation | SNOMED | (various) | Clinical observations. |
| Device | SNOMED | (various) | Medical devices. |
| Specimen | SNOMED | (various) | Specimen types. |
| Visit | Visit | Visit | OMOP-defined visit types. |
| Unit | UCUM | Unit | Units of measure. |
| Race | Race | Race | OMOP-defined race categories. |
| Ethnicity | Ethnicity | Ethnicity | OMOP-defined ethnicity categories. |
| Gender | Gender | Gender | OMOP-defined gender categories. |

## Key Workflow
1. Search for concept by clinical term using `search_concepts`
2. If you find a non-standard concept, use `get_concept_relationships` with
   relationship_id='Maps to' to find the standard equivalent
3. Use `get_concept_ancestors` / `get_concept_descendants` to navigate hierarchy
4. Use `preview_concept_set` to resolve a concept set with descendants for cohort building
"""

    @mcp.resource("omop://conventions/query-rules")
    async def query_rules() -> str:
        """Rules and conventions for writing correct OMOP CDM queries."""
        return """# OMOP CDM Query Rules

## Standard Concept Rules
- Only standard concepts (standard_concept = 'S') participate in hierarchy
  relationships (concept_ancestor). Non-standard concepts have NO ancestors/descendants.
- concept_id = 0 means "unmapped" — the source record had no standard mapping.
- Always use `search_concepts` to find concept_ids. Never guess or hardcode them.

## Join Conventions
- Always join clinical tables to `person` via person_id for demographics.
- Always join `*_concept_id` columns to `concept` for human-readable names.
- Use `concept_ancestor` for hierarchy queries (e.g., "all diabetes subtypes"),
  never manually enumerate descendant concept_ids.

## Anti-Patterns — Do NOT
- **String-match on source_value columns**: source_value is site-specific, non-portable,
  and may contain PHI. Always query via concept_id.
- **Hardcode concept_ids without verification**: Concept_ids can differ between vocabulary
  versions. Always verify via `search_concepts` first.
- **Skip concept_ancestor for hierarchy queries**: Manually listing descendants misses
  newly added concepts and is error-prone.
- **Use non-standard concepts in cohort definitions**: Hierarchy navigation and
  concept set resolution only work with standard concepts.

## Temporal Conventions
- `observation_period` defines each patient's valid data window — events outside
  it are unreliable and may be data artifacts.
- Always consider requiring continuous observation before/after index date to
  avoid immortal time bias.
- Drug eras and condition eras are precomputed temporal aggregations — prefer
  them over raw exposure/occurrence tables for duration-based analyses.
"""

    @mcp.resource("omop://conventions/health-economics")
    async def health_economics_guide() -> str:
        """Guide to OMOP health economics and derived element tables."""
        return """# Health Economics & Derived Element Tables

## Health Economics Tables

### cost
Links cost data to any clinical event via a generic foreign key pattern:
- `cost_event_id` = the primary key of the linked clinical record
- `cost_domain_id` = the domain of the linked record ('Visit', 'Drug', 'Procedure', etc.)

This means cost rows are NOT joined by a single FK column. Instead:
```sql
-- Cost for visits
SELECT c.* FROM cost c
WHERE c.cost_domain_id = 'Visit'
-- c.cost_event_id references visit_occurrence.visit_occurrence_id

-- Cost for drugs
SELECT c.* FROM cost c
WHERE c.cost_domain_id = 'Drug'
-- c.cost_event_id references drug_exposure.drug_exposure_id
```

Key columns:
- `total_charge`: amount billed
- `total_cost`: actual cost incurred
- `total_paid`: total amount paid (= paid_by_payer + paid_by_patient)
- `paid_by_payer`, `paid_by_patient`: payer vs patient split
- `paid_patient_copay`, `paid_patient_coinsurance`, `paid_patient_deductible`: patient cost breakdown
- `currency_concept_id`: currency (44818668 = USD)
- `payer_plan_period_id`: FK to payer_plan_period for insurance context

### payer_plan_period
Tracks insurance enrollment spans per patient:
- Each row = one continuous enrollment period under one payer/plan
- `payer_concept_id`: standardized payer (Medicare=280, Medicaid=289, Private=327)
- Use to determine insurance status at time of a clinical event

## Derived Element Tables

### drug_era
Precomputed from `drug_exposure` — collapses overlapping/adjacent drug exposures
of the same ingredient into continuous eras:
- `drug_concept_id`: always at the Ingredient level (not Clinical Drug)
- `drug_exposure_count`: number of raw exposures collapsed into this era
- `gap_days`: total gap days within the era

### condition_era
Precomputed from `condition_occurrence` — collapses condition records with
<=30 day gaps into continuous eras:
- `condition_occurrence_count`: number of raw occurrences in this era

### dose_era
Precomputed from `drug_exposure` — identifies periods of constant dose:
- `dose_value` + `unit_concept_id`: the constant dose during this period

## When to Use Eras vs Raw Tables

| Question | Use |
|:---------|:----|
| Was the patient ever on Drug X? | drug_era (simpler) |
| How long was the patient on Drug X? | drug_era (pre-collapsed) |
| What was the exact prescription date? | drug_exposure (raw detail) |
| What dose was prescribed? | dose_era or drug_exposure |
| How many refills? | drug_exposure (has refills column) |
| Duration of a chronic condition? | condition_era |
| Date of initial diagnosis? | condition_occurrence |

## Common Query Patterns

```sql
-- Total drug cost by ingredient
SELECT c2.concept_name AS drug_name,
       SUM(co.total_paid) AS total_paid
FROM cost co
JOIN drug_exposure de ON co.cost_event_id = de.drug_exposure_id
    AND co.cost_domain_id = 'Drug'
JOIN concept c2 ON de.drug_concept_id = c2.concept_id
GROUP BY c2.concept_name
ORDER BY total_paid DESC;

-- Average visit cost by payer type
SELECT c2.concept_name AS payer,
       AVG(co.total_paid) AS avg_paid
FROM cost co
JOIN payer_plan_period pp ON co.payer_plan_period_id = pp.payer_plan_period_id
JOIN concept c2 ON pp.payer_concept_id = c2.concept_id
GROUP BY c2.concept_name;

-- Patients with drug era > 1 year
SELECT COUNT(DISTINCT person_id) AS long_term_patients,
       c.concept_name AS drug_name
FROM drug_era de
JOIN concept c ON de.drug_concept_id = c.concept_id
WHERE de.drug_era_end_date - de.drug_era_start_date > 365
GROUP BY c.concept_name
ORDER BY long_term_patients DESC;
```
"""

    @mcp.resource("omop://conventions/common-mistakes")
    async def common_mistakes() -> str:
        """Common mistakes LLMs and analysts make with OMOP data."""
        return """# Common OMOP Mistakes

## 1. Hallucinating concept_ids
LLMs frequently invent concept_ids that don't exist. ALWAYS use `search_concepts`
to find real concept_ids. Never assume a concept_id from memory.

## 2. Querying source_value instead of concept_id
source_value is the raw text from the source system (e.g., "DM2", "E11.9"). It is
site-specific, non-portable across institutions, and may contain PHI. Always use
the mapped concept_id for analysis.

## 3. Missing observation period filter
Patients without sufficient observation time before/after an event produce biased
results. Always check that patients have continuous observation covering the
analysis window. The `observation_period` table defines valid data spans.

## 4. Using non-standard concepts in cohort definitions
Non-standard concepts (ICD10CM, NDC, CPT4) lack hierarchy relationships.
Cohort definitions using them cannot expand via concept_ancestor, missing
clinically equivalent codes. Always map to standard concepts first.

## 5. Confusing concept_id columns
Each clinical table has multiple `*_concept_id` columns:
- `condition_concept_id` = the standard concept (use this)
- `condition_source_concept_id` = the source vocabulary concept
- `condition_type_concept_id` = how the record was captured (EHR, claim, etc.)
Use the primary `*_concept_id` for clinical queries.

## 6. Ignoring invalid_reason
Concepts with invalid_reason = 'D' (deleted) or 'U' (updated) should not be used.
Always filter with `invalid_reason IS NULL` or use valid_only=True in search.

## 7. Not using 'Maps to' for non-standard concepts
When you find an ICD10CM or NDC code, use `get_concept_relationships` with
relationship_id='Maps to' to find the standard SNOMED/RxNorm equivalent.
"""
