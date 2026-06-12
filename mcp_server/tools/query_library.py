"""Query Library tools: search and retrieve OHDSI community SQL query templates.

Data source: OHDSI/QueryLibrary (Apache 2.0)
  - ~200 markdown files with SQL queries, metadata, and documentation
  - Organized by category: drug, condition, person, measurement, etc.

Data must be downloaded first via scripts/download_query_library.sh.
"""

from mcp.server.fastmcp import FastMCP

from core.query_library import search_query_patterns_core, get_query_core


def register_query_library_tools(mcp: FastMCP):

    @mcp.tool()
    async def search_query_patterns(
        keyword: str,
        category: str | None = None,
        limit: int = 15,
    ) -> str:
        """Search OHDSI QueryLibrary for community-approved SQL query templates.

        The QueryLibrary contains ~200 SQL query patterns covering common OMOP CDM
        analyses: drug exposures, condition prevalence, patient demographics, etc.
        Each template includes parameterized SQL with @cdm/@vocab schema placeholders.

        Use this to find proven query patterns before writing SQL from scratch.

        Args:
            keyword: Search term (matches query name and description)
            category: Filter by category (e.g., drug, condition, person, drug_era,
                      drug_exposure, condition_era, general, observation_period)
            limit: Maximum results (1-20). Default: 15
        """
        result = search_query_patterns_core(keyword, category, limit)

        if isinstance(result, str):
            return result

        results, total_matches = result

        if not results:
            fstr = f" (category={category})" if category else ""
            return f"No query patterns found for '{keyword}'{fstr}."

        lines = [
            f"## Query Pattern Search: '{keyword}'",
            f"*{len(results)} of {total_matches} matches shown.*",
            "",
            "| query_id | name | category | cdm_version |",
            "|:---------|:-----|:---------|:------------|",
        ]

        for entry in results:
            qid = entry["query_id"]
            name = entry["name"][:55]
            group = entry["group"]
            ver = entry["cdm_version"]
            lines.append(f"| {qid} | {name} | {group} | {ver} |")

        lines.append("")
        lines.append("Use `get_query(query_id)` to retrieve the full SQL template.")
        return "\n".join(lines)

    @mcp.tool()
    async def get_query(query_id: str) -> str:
        """Retrieve a full SQL query template from the OHDSI QueryLibrary.

        Returns the complete query with SQL, parameters, and expected output columns.
        Replace @cdm and @vocab placeholders with actual schema names before execution.

        Args:
            query_id: The query ID from search_query_patterns results (e.g., 'D01', 'CE05')
        """
        result = get_query_core(query_id)

        if isinstance(result, str):
            return result

        entry = result
        lines = [f"## {entry['full_name']}"]
        lines.append("")

        if entry["group"]:
            lines.append(f"**Category**: {entry['group']}")
        if entry["author"]:
            lines.append(f"**Author**: {entry['author']}")
        if entry["cdm_version"]:
            lines.append(f"**CDM Version**: {entry['cdm_version']}")

        if entry["description"]:
            lines.append("")
            lines.append("### Description")
            lines.append(entry["description"])

        if entry["sql"]:
            lines.append("")
            lines.append("### SQL")
            lines.append("```sql")
            lines.append(entry["sql"])
            lines.append("```")
            lines.append("")
            lines.append(
                "*Replace `@cdm` with your CDM schema name (e.g., `main_cdm`) "
                "and `@vocab` with your vocabulary schema name (e.g., `main_vocab`) before executing.*"
            )

        if entry["input"] and entry["input"].lower() != "none":
            lines.append("")
            lines.append("### Input Parameters")
            lines.append(entry["input"])

        if entry["output"]:
            lines.append("")
            lines.append("### Output Columns")
            lines.append(entry["output"])

        return "\n".join(lines)
