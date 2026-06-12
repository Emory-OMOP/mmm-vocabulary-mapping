"""table_schema tools: Get OMOP CDM table schemas as XML for SQL authoring."""

from mcp.server.fastmcp import FastMCP

from omop_vocab_core.table_schema import list_cdm_tables_core, get_table_schema_core


def register_table_schema_tools(mcp: FastMCP):

    @mcp.tool()
    async def list_cdm_tables(category: str | None = None) -> str:
        """List available OMOP CDM tables grouped by category.

        Call this to discover which tables exist before requesting
        a specific table's schema with get_table_schema.

        Args:
            category: Filter by category — 'clinical', 'vocabulary', 'system', 'health_economics', or 'derived'. Default: all.
        """
        return list_cdm_tables_core(category)

    @mcp.tool()
    async def get_table_schema(table_name: str) -> str:
        """Get the column schema for a specific OMOP CDM table as XML.

        Returns column names, types, primary/foreign keys, vocabulary
        hints, and restricted-column flags. Use this to understand a
        table's structure before writing SQL for a SQL execution tool.

        Args:
            table_name: OMOP CDM table name (e.g. 'condition_occurrence', 'person', 'drug_exposure')
        """
        return get_table_schema_core(table_name)
