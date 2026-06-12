"""Standard mapping tool: trace non-standard concepts to standard equivalents."""

from mcp.server.fastmcp import FastMCP

from omop_vocab_core.standard_mapping import trace_standard_mapping_core
from tools._staging_mixin import stage_concepts, result_id_line


def _format_mapping(result: dict, result_id: int | None) -> str:
    """Format mapping chain as markdown without concept_ids."""
    if result.get("error"):
        lines = ["## Standard Mapping", "", result["error"]]
        lines.append(result_id_line(result_id))
        return "\n".join(lines)

    source = result.get("source") or {}
    target = result.get("target") or {}
    chain = result.get("chain", [])
    hops = result.get("hops", 0)

    source_name = source.get("concept_name", "Unknown")
    target_name = target.get("concept_name", "Unknown")

    lines = [
        f"## Standard Mapping: {source_name} → {target_name}",
        f"*{hops} hop(s)*",
        "",
    ]

    if hops == 0:
        lines.append(f"**{source_name}** is already a standard concept "
                      f"({source.get('vocabulary_id', '')} / {source.get('concept_class_id', '')}).")
    else:
        # Show chain steps: concept names + relationship, no IDs
        for i, step in enumerate(chain):
            rel = step.get("relationship_id", "Maps to")
            c = step.get("concept", {})
            c_name = c.get("concept_name", "?")
            c_vocab = c.get("vocabulary_id", "?")
            c_std = c.get("standard_concept", "")
            std_marker = " ✓ Standard" if c_std == "S" else ""
            if i == 0:
                lines.append(f"1. **{source_name}** ({source.get('vocabulary_id', '')})")
            lines.append(f"   → *{rel}*")
            lines.append(f"{i + 2}. **{c_name}** ({c_vocab}){std_marker}")

    lines.append(result_id_line(result_id))
    return "\n".join(lines)


def register_standard_mapping_tools(mcp: FastMCP):

    @mcp.tool()
    async def trace_standard_mapping(
        concept_id: int,
    ) -> str:
        """Trace a non-standard or source concept to its standard OMOP equivalent.

        Follows the 'Maps to' relationship chain from the input concept until a
        Standard concept (standard_concept = 'S') is reached. Returns the full
        chain showing each mapping step.

        Use this when you have a source code (ICD-10, CPT4, etc.) or non-standard
        concept and need to find the standard SNOMED/RxNorm/LOINC equivalent.
        This replaces the manual workflow of calling get_concept_relationships
        with relationship_id='Maps to', then looking up the result.

        If the input concept is already standard, returns it immediately with
        zero hops.

        Args:
            concept_id: The OMOP concept_id to trace (can be standard or non-standard)
        """
        result = trace_standard_mapping_core(concept_id)

        # Collect all concepts in the mapping chain for staging
        chain_concepts = []
        source = result.get("source")
        if source and source.get("concept_id"):
            chain_concepts.append(source)
        for step in result.get("chain", []):
            c = step.get("concept")
            if c and c.get("concept_id"):
                chain_concepts.append(c)

        params = dict(concept_id=concept_id)
        result_id = stage_concepts("trace_standard_mapping", params, chain_concepts)

        return _format_mapping(result, result_id)
