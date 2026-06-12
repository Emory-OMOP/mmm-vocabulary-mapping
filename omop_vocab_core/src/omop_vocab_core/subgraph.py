"""BFS subgraph exploration over OMOP concept relationships.

Algorithm ported from omop-graph's traverse.py, adapted for DuckDB
with batch edge fetching.
"""

from __future__ import annotations

from collections import deque

from .graph_cache import GraphContext
from .graph_types import PredicateKind, SubgraphResult


def explore_subgraph(
    ctx: GraphContext,
    seed_concept_ids: list[int],
    *,
    max_depth: int = 2,
    max_nodes: int = 50,
    predicate_kinds: set[PredicateKind] | None = None,
) -> SubgraphResult:
    """BFS from seed concepts, returning a neighborhood subgraph.

    Parameters
    ----------
    ctx : GraphContext
        Graph context with DuckDB connection and caches.
    seed_concept_ids : list of int
        Starting concept_ids.
    max_depth : int
        Maximum BFS depth (default 2, max 4).
    max_nodes : int
        Maximum nodes to include (default 50, max 200).
    predicate_kinds : set of PredicateKind, optional
        Restrict traversal to these edge types. None = all edges.
    """
    max_depth = min(max_depth, 4)
    max_nodes = min(max_nodes, 200)

    rel_ids = ctx.relationship_ids_for_kinds(predicate_kinds) if predicate_kinds else None

    visited: set[int] = set(seed_concept_ids)
    queue: deque[tuple[int, int]] = deque((sid, 0) for sid in seed_concept_ids)
    edge_set: set[tuple[int, str, int]] = set()
    truncated = False

    while queue:
        # Drain current depth level for batch fetching
        level_nodes = []
        current_depth = queue[0][1] if queue else 0
        while queue and queue[0][1] == current_depth:
            node, d = queue.popleft()
            if d < max_depth:
                level_nodes.append((node, d))

        if not level_nodes:
            continue

        frontier_ids = [n for n, _ in level_nodes]
        edges_by_src = ctx.outgoing_edges_batch(frontier_ids, rel_ids)

        for cur, d in level_nodes:
            for e in edges_by_src.get(cur, []):
                edge_key = (e.subject_id, e.predicate_id, e.object_id)
                if edge_key in edge_set:
                    continue
                edge_set.add(edge_key)

                if e.object_id not in visited:
                    if len(visited) >= max_nodes:
                        truncated = True
                        continue
                    visited.add(e.object_id)
                    queue.append((e.object_id, d + 1))

    # Collect all concept_ids referenced in edges (may exceed visited set)
    edge_concept_ids = set()
    for src, _, tgt in edge_set:
        edge_concept_ids.add(src)
        edge_concept_ids.add(tgt)
    all_ids = visited | edge_concept_ids

    # Enrich nodes and edges with metadata
    concept_data = ctx.concept_views_batch(list(all_ids))

    nodes = []
    for cid in sorted(visited):
        c = concept_data.get(cid)
        if c:
            nodes.append(c)
        else:
            nodes.append({"concept_id": cid, "concept_name": f"Unknown ({cid})"})

    edges = []
    for src, rel, tgt in sorted(edge_set):
        pred = ctx.predicate(rel)
        src_data = concept_data.get(src, {})
        tgt_data = concept_data.get(tgt, {})
        edges.append({
            "source_id": src,
            "source_name": src_data.get("concept_name", f"Unknown ({src})"),
            "relationship_id": rel,
            "relationship_name": pred.relationship_name if pred else rel,
            "target_id": tgt,
            "target_name": tgt_data.get("concept_name", f"Unknown ({tgt})"),
        })

    return SubgraphResult(
        nodes=nodes,
        edges=edges,
        seed_ids=seed_concept_ids,
        depth=max_depth,
        truncated=truncated,
    )
