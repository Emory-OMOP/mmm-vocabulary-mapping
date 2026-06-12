"""Graph exploration tool: BFS subgraph traversal from seed concepts."""

from mcp.server.fastmcp import FastMCP

from omop_vocab_core.graph_cache import graph_context
from omop_vocab_core.graph_types import PredicateKind
from omop_vocab_core.subgraph import explore_subgraph
from tools._staging_mixin import stage_concepts, result_id_line


def _parse_edge_types(edge_types: str | None) -> set[PredicateKind] | None:
    if not edge_types:
        return None
    valid = {k.value for k in PredicateKind}
    kinds = set()
    for token in edge_types.split(","):
        token = token.strip().lower()
        if token in valid:
            kinds.add(PredicateKind(token))
    return kinds or None


def _format_subgraph(result, result_id: int | None) -> str:
    # Build node index: concept_id → row_index for edge display
    node_index = {}
    for idx, n in enumerate(result.nodes):
        cid = n.get("concept_id")
        if cid is not None:
            node_index[cid] = idx

    lines = [
        f"## Concept Graph Exploration",
        "",
        f"*{len(result.nodes)} node(s), {len(result.edges)} edge(s), "
        f"depth {result.depth}*",
    ]
    if result.truncated:
        lines.append("*Note: Results truncated at node limit.*")
    lines.append("")

    # Node table — no concept_ids
    lines.append(f"### Nodes (result_id: {result_id})")
    lines.append("| # | concept_name | domain | vocab | class | std |")
    lines.append("|---|:-------------|:-------|:------|:------|:----|")
    for idx, n in enumerate(result.nodes):
        std = "S" if n.get("standard_concept") == "S" else ""
        lines.append(
            f"| {idx} | {str(n.get('concept_name', '?'))[:50]} | "
            f"{n.get('domain_id', '?')} | {n.get('vocabulary_id', '?')} | "
            f"{n.get('concept_class_id', '?')} | {std} |"
        )

    lines.append("")

    # Edge table — use row indices instead of concept_ids
    lines.append("### Edges")
    lines.append("| source (# name) | relationship | target (# name) |")
    lines.append("|:-----------------|:-------------|:-----------------|")
    for e in result.edges:
        src_idx = node_index.get(e["source_id"], "?")
        tgt_idx = node_index.get(e["target_id"], "?")
        src = f"#{src_idx} {str(e['source_name'])[:30]}"
        tgt = f"#{tgt_idx} {str(e['target_name'])[:30]}"
        lines.append(f"| {src} | {e['relationship_name']} | {tgt} |")

    lines.append(result_id_line(result_id))
    return "\n".join(lines)


def register_exploration_tools(mcp: FastMCP):

    @mcp.tool()
    async def explore_concept_graph(
        concept_ids: str,
        max_depth: int = 2,
        max_nodes: int = 50,
        edge_types: str | None = None,
    ) -> str:
        """Explore the neighborhood around one or more OMOP concepts via BFS.

        Starting from seed concept(s), traverses outgoing CONCEPT_RELATIONSHIP
        edges up to max_depth hops, returning all discovered nodes and edges
        as a subgraph.

        Unlike get_concept_relationships (single-hop, flat table) or
        get_concept_ancestors/descendants (precomputed hierarchy only), this
        tool follows ALL relationship types across multiple hops, revealing
        the full neighborhood graph.

        Use this to understand what's around a concept: its mappings, attributes,
        related drugs/conditions, and how it connects to other vocabularies.

        Args:
            concept_ids: Comma-separated OMOP concept_ids to start from
            max_depth: BFS depth (1-4, default 2)
            max_nodes: Maximum nodes to return (1-200, default 50)
            edge_types: Optional comma-separated edge type filter.
                        Values: ontological, mapping, versioning, attribute, metadata.
                        Default: all edge types.
        """
        seeds = [int(s.strip()) for s in concept_ids.split(",") if s.strip().isdigit()]
        if not seeds:
            return "Error: provide at least one valid concept_id."

        max_depth = min(max(1, max_depth), 4)
        max_nodes = min(max(1, max_nodes), 200)
        predicate_kinds = _parse_edge_types(edge_types)

        with graph_context() as ctx:
            result = explore_subgraph(
                ctx,
                seeds,
                max_depth=max_depth,
                max_nodes=max_nodes,
                predicate_kinds=predicate_kinds,
            )

        # Stage node concepts
        staging_nodes = []
        for n in result.nodes:
            if n.get("concept_id") is not None:
                staging_nodes.append({
                    "concept_id": n["concept_id"],
                    "concept_name": n.get("concept_name"),
                    "domain_id": n.get("domain_id"),
                    "vocabulary_id": n.get("vocabulary_id"),
                    "concept_class_id": n.get("concept_class_id"),
                    "standard_concept": n.get("standard_concept"),
                })

        params = dict(
            concept_ids=seeds, max_depth=max_depth,
            max_nodes=max_nodes, edge_types=edge_types,
        )
        result_id = stage_concepts("explore_concept_graph", params, staging_nodes)

        return _format_subgraph(result, result_id)
