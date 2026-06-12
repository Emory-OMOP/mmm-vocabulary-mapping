"""Graph pathfinding tool: find shortest paths between two OMOP concepts."""

from mcp.server.fastmcp import FastMCP

from omop_vocab_core.graph_cache import graph_context
from omop_vocab_core.graph_types import PredicateKind
from omop_vocab_core.pathfinding import find_ranked_paths
from tools._staging_mixin import stage_concepts, result_id_line

_VALID_EDGE_TYPES = {k.value for k in PredicateKind}


def _parse_edge_types(edge_types: str | None) -> set[PredicateKind] | None:
    if not edge_types:
        return None
    kinds = set()
    for token in edge_types.split(","):
        token = token.strip().lower()
        if token in _VALID_EDGE_TYPES:
            kinds.add(PredicateKind(token))
    return kinds or None


def _collect_path_concepts(explanations, source_view, target_view, source_id, target_id):
    """Collect unique concepts from all paths, preserving discovery order."""
    seen = set()
    concepts = []

    def _add(cid, view):
        if cid not in seen and view:
            seen.add(cid)
            concepts.append({
                "concept_id": cid,
                "concept_name": view.get("concept_name"),
                "domain_id": view.get("domain_id"),
                "vocabulary_id": view.get("vocabulary_id"),
                "concept_class_id": view.get("concept_class_id"),
                "standard_concept": view.get("standard_concept"),
            })

    # Add source and target first
    _add(source_id, source_view)
    _add(target_id, target_view)

    # Add intermediate concepts from path steps
    for expl in explanations:
        for step in expl.step_details:
            _add(step["subject_id"], {
                "concept_name": step["subject_name"],
                "vocabulary_id": step.get("subject_vocab"),
            })
            _add(step["object_id"], {
                "concept_name": step["object_name"],
                "vocabulary_id": step.get("object_vocab"),
            })

    return concepts


def _format_paths(explanations, source_name, target_name, result_id) -> str:
    lines = [
        f"## Paths: {source_name} → {target_name}",
        "",
    ]

    if not explanations:
        lines.append("No path found within the depth limit.")
        lines.append(result_id_line(result_id))
        return "\n".join(lines)

    lines.append(f"*{len(explanations)} path(s) found.*\n")

    for i, expl in enumerate(explanations, 1):
        p = expl.profile
        lines.append(f"### Path {i} ({p.hops} hop{'s' if p.hops != 1 else ''})")

        # Profile summary
        tags = []
        if p.ontological_edges:
            tags.append(f"{p.ontological_edges} ontological")
        if p.mapping_edges:
            tags.append(f"{p.mapping_edges} mapping")
        if p.metadata_edges:
            tags.append(f"{p.metadata_edges} metadata")
        if p.vocab_switches:
            tags.append(f"{p.vocab_switches} vocab switch{'es' if p.vocab_switches != 1 else ''}")
        if p.non_standard_concepts:
            tags.append(f"{p.non_standard_concepts} non-standard")
        if p.invalid_concepts:
            tags.append(f"{p.invalid_concepts} invalid")
        if tags:
            lines.append(f"*Edges: {', '.join(tags)}*\n")

        # Step-by-step — concept names only, no IDs
        if not expl.step_details:
            lines.append("Source and target are the same concept.\n")
            continue

        for j, step in enumerate(expl.step_details):
            if j == 0:
                lines.append(
                    f"1. **{step['subject_name']}** ({step['subject_vocab']})"
                )
            lines.append(
                f"   →  *{step['predicate_name']}* [{step['predicate_kind']}]"
            )
            lines.append(
                f"{j + 2}. **{step['object_name']}** ({step['object_vocab']})"
            )
        lines.append("")

    lines.append(result_id_line(result_id))
    return "\n".join(lines)


def register_pathfinding_tools(mcp: FastMCP):

    @mcp.tool()
    async def find_concept_paths(
        source_concept_id: int,
        target_concept_id: int,
        max_depth: int = 6,
        max_paths: int = 5,
        edge_types: str | None = None,
    ) -> str:
        """Find shortest paths between two OMOP concepts through the relationship graph.

        Walks the CONCEPT_RELATIONSHIP edges (not the precomputed ancestor table)
        using bidirectional BFS. Returns ranked paths with step-by-step explanations
        showing how two concepts are connected through intermediate concepts and
        relationship types.

        Use this to answer: "How is concept A related to concept B?", discover
        cross-vocabulary mapping chains, or understand how drug/condition/measurement
        concepts connect through SNOMED, RxNorm, LOINC, etc.

        Args:
            source_concept_id: Starting OMOP concept_id
            target_concept_id: Target OMOP concept_id
            max_depth: Maximum path length in hops (1-8, default 6)
            max_paths: Maximum paths to return (1-20, default 5)
            edge_types: Optional comma-separated edge type filter.
                        Values: ontological, mapping, versioning, attribute, metadata.
                        Default: all edge types.
        """
        max_depth = min(max(1, max_depth), 8)
        max_paths = min(max(1, max_paths), 20)
        predicate_kinds = _parse_edge_types(edge_types)

        with graph_context() as ctx:
            source_view = ctx.concept_view(source_concept_id)
            target_view = ctx.concept_view(target_concept_id)
            source_name = source_view.get("concept_name", "Unknown") if source_view else "Unknown"
            target_name = target_view.get("concept_name", "Unknown") if target_view else "Unknown"

            explanations = find_ranked_paths(
                ctx,
                source_concept_id,
                target_concept_id,
                predicate_kinds=predicate_kinds,
                max_depth=max_depth,
                max_paths=max_paths,
            )

        # Collect and stage all unique concepts from paths
        path_concepts = _collect_path_concepts(
            explanations, source_view, target_view,
            source_concept_id, target_concept_id,
        )
        params = dict(
            source_concept_id=source_concept_id,
            target_concept_id=target_concept_id,
            max_depth=max_depth, max_paths=max_paths,
            edge_types=edge_types,
        )
        result_id = stage_concepts("find_concept_paths", params, path_concepts)

        return _format_paths(explanations, source_name, target_name, result_id)
