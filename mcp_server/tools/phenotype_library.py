"""Phenotype Library tools: search and retrieve OHDSI curated cohort definitions.

Data source: OHDSI/PhenotypeLibrary (Apache 2.0)
  - Cohorts.csv: metadata catalog (~1,100 rows)
  - inst/cohorts/{id}.json: CIRCE cohort definition JSONs

Data must be downloaded first via scripts/download_phenotype_library.sh.
"""

import json

from mcp.server.fastmcp import FastMCP

from core.phenotype import (
    search_phenotypes_core,
    get_phenotype_core,
    format_domains,
)

_MAX_JSON_PREVIEW = 500


def _describe_end_strategy_brief(end_strat: dict) -> str:
    """One-line description of a CIRCE EndStrategy block."""
    if "DateOffset" in end_strat:
        d = end_strat["DateOffset"]
        field = d.get("DateField", "EndDate")
        offset = d.get("Offset", 0)
        return f"DateOffset ({field} + {offset} days)"
    if "CustomEra" in end_strat:
        gap = end_strat["CustomEra"].get("GapDays", 0)
        return f"DrugEra (gap {gap} days)"
    return "Custom"


def register_phenotype_library_tools(mcp: FastMCP):

    @mcp.tool()
    async def search_phenotypes(
        keyword: str,
        domain: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> str:
        """Search OHDSI PhenotypeLibrary for curated CIRCE cohort definitions.

        The PhenotypeLibrary contains 1,100+ peer-reviewed cohort definitions
        covering conditions, drugs, procedures, and more. Each phenotype is a
        complete CIRCE JSON ready for compilation to SQL.

        Use this tool to find reusable cohort definitions before building
        from scratch. Found phenotypes can be retrieved with `get_phenotype`
        and compiled with `compile_cohort_definition` (circe-compiler server).

        Args:
            keyword: Search term (matches cohort name, description, and tags)
            domain: Filter by clinical domain: condition, drug, procedure,
                    measurement, observation, visit, device, death
            status: Filter by review status: Accepted, Pending, Withdrawn
            limit: Maximum results (1-30). Default: 20
        """
        result = search_phenotypes_core(keyword, domain, status, limit)

        if isinstance(result, str):
            return result

        results, total_matches = result

        if not results:
            filter_desc = []
            if domain:
                filter_desc.append(f"domain={domain}")
            if status:
                filter_desc.append(f"status={status}")
            fstr = f" ({', '.join(filter_desc)})" if filter_desc else ""
            return f"No phenotypes found for '{keyword}'{fstr}."

        lines = [
            f"## Phenotype Search: '{keyword}'",
            f"*{len(results)} of {total_matches} matches shown.*",
            "",
            "| cohort_id | name | status | domains | concept_sets | inclusion_rules |",
            "|:----------|:-----|:-------|:--------|:-------------|:----------------|",
        ]

        for entry in results:
            cid = entry["cohortId"]
            name = (entry.get("cohortName") or "")[:60]
            st = entry.get("status") or ""
            domains = format_domains(entry)
            cs = entry.get("numberOfConceptSets") or "0"
            ir = entry.get("numberOfInclusionRules") or "0"
            lines.append(f"| {cid} | {name} | {st} | {domains} | {cs} | {ir} |")

        lines.append("")
        lines.append("Use `get_phenotype(cohort_id)` to retrieve the full CIRCE JSON.")
        return "\n".join(lines)

    @mcp.tool()
    async def get_phenotype(
        cohort_id: int,
        return_mode: str = "summary",
    ) -> str:
        """Retrieve a full CIRCE cohort definition JSON from the PhenotypeLibrary.

        Returns cohort metadata and definition. Use return_mode="summary"
        (default) for a compact overview with concept set names and a
        truncated JSON preview. Use return_mode="full" only for debugging
        when you need the raw CIRCE JSON.

        Most callers should use compile_cohort_definition(phenotype_id=...)
        instead — it loads the definition directly without needing this tool.

        Args:
            cohort_id: The cohort ID from search_phenotypes results
            return_mode: "summary" (default, compact) or "full" (debugging only — returns raw CIRCE JSON)
        """
        result = get_phenotype_core(cohort_id)

        if isinstance(result, str):
            return result

        lines = [f"## Phenotype: {result['cohort_name']}"]
        lines.append("")

        if result.get("status"):
            lines.append(f"**Status**: {result['status']}")
        if result.get("logic_description"):
            lines.append(f"**Description**: {result['logic_description']}")
        if result.get("hash_tag"):
            lines.append(f"**Tags**: {result['hash_tag']}")
        if result.get("domains"):
            lines.append(f"**Domains**: {result['domains']}")

        cohort_json_str = result["cohort_json"]

        if return_mode == "full":
            lines.append("")
            lines.append("```json")
            lines.append(cohort_json_str)
            lines.append("```")
            return "\n".join(lines)

        # summary mode: parse JSON for concept set / inclusion rule names
        try:
            defn = json.loads(cohort_json_str)
        except json.JSONDecodeError:
            defn = {}

        cs_items = defn.get("ConceptSets") or []
        cs_names = [cs.get("name", f"Unnamed-{i}") for i, cs in enumerate(cs_items)]
        lines.append(
            f"**Concept Sets ({len(cs_names)})**: "
            + (", ".join(cs_names) if cs_names else "—")
        )

        ir_items = defn.get("InclusionRules") or []
        ir_names = [ir.get("name", f"Unnamed-{i}") for i, ir in enumerate(ir_items)]
        lines.append(
            f"**Inclusion Rules ({len(ir_names)})**: "
            + (", ".join(ir_names) if ir_names else "—")
        )

        # End strategy hint
        end_strat = defn.get("EndStrategy")
        if end_strat:
            lines.append(f"**End Strategy**: {_describe_end_strategy_brief(end_strat)}")

        # Capped JSON preview
        lines.append("")
        lines.append("### CIRCE JSON Preview")
        lines.append("```json")
        lines.append(cohort_json_str[:_MAX_JSON_PREVIEW])
        if len(cohort_json_str) > _MAX_JSON_PREVIEW:
            lines.append("```")
            lines.append(
                f"*[Truncated — {len(cohort_json_str):,} chars total. "
                f"Use `compile_cohort_definition(phenotype_id={cohort_id})` to compile/execute.]*"
            )
        else:
            lines.append("```")

        return "\n".join(lines)
