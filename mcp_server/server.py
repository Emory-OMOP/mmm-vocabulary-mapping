#!/usr/bin/env python3
"""OHDSI OMOP Vocabulary MCP Server.

Provides vocabulary lookup tools for an AI agent working with OMOP CDM data.
Queries a local DuckDB instance containing the full Athena vocabulary (7.4M concepts).
"""

import os
import sys
from pathlib import Path

# Add mcp_server/ to sys.path so submodule imports work when run directly
sys.path.insert(0, str(Path(__file__).parent))

from mcp.server.fastmcp import FastMCP

from tools.search_concepts import register_search_concepts
from tools.concept_lookup import register_concept_lookup
from tools.concept_hierarchy import register_hierarchy_tools
from tools.concept_relationships import register_relationship_tools
from tools.concept_set import register_concept_set_tools
from tools.table_schema import register_table_schema_tools
from tools.phenotype_library import register_phenotype_library_tools
from tools.query_library import register_query_library_tools
from tools.graph_pathfinding import register_pathfinding_tools
from tools.graph_exploration import register_exploration_tools
from tools.term_grounding import register_grounding_tools
from tools.standard_mapping import register_standard_mapping_tools
from tools.standard_via_nonstandard import register_standard_via_nonstandard
from tools.concept_set_resolver import register_concept_set_resolver_tools
from tools.phenotype_simplifier import register_phenotype_simplifier_tools
from tools.result_curation import register_result_curation_tools
from resources.omop_docs import register_resources
from prompts.concept_search import register_prompts
from omop_vocab_core.staging import init_staging_db

mcp = FastMCP(
    "ohdsi-vocab",
    instructions=(
        "OHDSI OMOP Vocabulary search and navigation tools. "
        "Provides deep access to 7.4M+ standardized clinical concepts "
        "from SNOMED, RxNorm, LOINC, ICD10CM, and 60+ other vocabularies "
        "via a local DuckDB instance.\n\n"
        "AUTO-STAGING: Every concept-returning tool automatically stages its "
        "results in a server-side database. Responses include a result_id and "
        "row indices — concept_ids are hidden. You never need to extract, "
        "remember, or relay concept_ids between tools.\n\n"
        "WORKFLOW — Exploration to construction:\n"
        "1. Search/explore: Use any tool (search_concepts, explore_concept_graph, "
        "find_concept_paths, ground_clinical_term, etc.). Results are auto-staged.\n"
        "2. Curate: Use cherry_pick_results(result_id, indices) to select specific "
        "concepts. Use exclude_from_result to filter, expand_descendants to add "
        "hierarchy, modify_result_flags to toggle include_descendants/is_excluded.\n"
        "3. Promote: Use keep_result(result_id, draft_name) to name a curated set.\n\n"
        "REFERENCE PATTERN: Always reference concepts by result_id and row index "
        "(e.g., 'from result 3, pick rows 0 and 2'). Never by concept_id. "
        "Use reveal_concept_ids only when raw IDs are specifically needed "
        "(e.g., ATLAS export, debugging)."
    ),
)

init_staging_db()

register_search_concepts(mcp)
register_concept_lookup(mcp)
register_hierarchy_tools(mcp)
register_relationship_tools(mcp)
register_concept_set_tools(mcp)
register_table_schema_tools(mcp)
register_phenotype_library_tools(mcp)
register_query_library_tools(mcp)
register_pathfinding_tools(mcp)
register_exploration_tools(mcp)
register_grounding_tools(mcp)
register_standard_mapping_tools(mcp)
register_standard_via_nonstandard(mcp)
register_concept_set_resolver_tools(mcp)
register_phenotype_simplifier_tools(mcp)
register_result_curation_tools(mcp)
register_resources(mcp)
register_prompts(mcp)


def main():
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "streamable-http":
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = int(os.environ.get("MCP_PORT", "8001"))
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
