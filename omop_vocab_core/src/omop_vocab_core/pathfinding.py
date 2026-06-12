"""Bidirectional BFS pathfinding with scoring over OMOP concept relationships.

Algorithm ported from omop-graph (UNSW/Australian Cancer Data Network),
adapted for DuckDB with batch edge fetching.
"""

from __future__ import annotations

from collections import defaultdict, deque

from .graph_cache import GraphContext
from .graph_types import (
    EdgeView,
    GraphPath,
    PathExplanation,
    PathProfile,
    PathStep,
    PredicateKind,
)


def _reconstruct_paths(
    source: int,
    target: int,
    meet: int,
    parents_fwd: dict[int, list[tuple[int, str]]],
    parents_bwd: dict[int, list[tuple[int, str]]],
    max_paths: int,
) -> list[GraphPath]:
    """Reconstruct all shortest paths through meeting node from BFS parent pointers."""

    def left_segments(n: int) -> list[tuple[PathStep, ...]]:
        if n == source:
            return [()]
        segs = []
        for parent, pred in parents_fwd[n]:
            for seg in left_segments(parent):
                segs.append(seg + (PathStep(parent, pred, n),))
                if len(segs) >= max_paths:
                    return segs
        return segs

    def right_segments(n: int) -> list[tuple[PathStep, ...]]:
        if n == target:
            return [()]
        segs = []
        for child, pred in parents_bwd[n]:
            for seg in right_segments(child):
                segs.append((PathStep(n, pred, child),) + seg)
                if len(segs) >= max_paths:
                    return segs
        return segs

    paths = []
    for left in left_segments(meet):
        for right in right_segments(meet):
            paths.append(GraphPath(steps=left + right))
            if len(paths) >= max_paths:
                return paths
    return paths


def _compute_profile(ctx: GraphContext, path: GraphPath) -> PathProfile:
    """Compute quality metrics for a path."""
    nodes = path.nodes()
    concept_data = ctx.concept_views_batch(list(nodes))

    invalid = 0
    non_standard = 0
    vocab_switches = 0
    ontological = 0
    mapping = 0
    metadata = 0

    prev_vocab = None
    for nid in nodes:
        c = concept_data.get(nid)
        if c is None:
            invalid += 1
            continue
        if c.get("invalid_reason"):
            invalid += 1
        if c.get("standard_concept") != "S":
            non_standard += 1
        vocab = c.get("vocabulary_id")
        if prev_vocab is not None and vocab != prev_vocab:
            vocab_switches += 1
        prev_vocab = vocab

    for step in path.steps:
        kind = ctx.predicate_kind(step.predicate_id)
        if kind == PredicateKind.ONTOLOGICAL:
            ontological += 1
        elif kind == PredicateKind.MAPPING:
            mapping += 1
        elif kind == PredicateKind.METADATA:
            metadata += 1

    return PathProfile(
        hops=path.hops,
        invalid_concepts=invalid,
        non_standard_concepts=non_standard,
        vocab_switches=vocab_switches,
        ontological_edges=ontological,
        mapping_edges=mapping,
        metadata_edges=metadata,
    )


def _build_explanation(ctx: GraphContext, path: GraphPath, profile: PathProfile) -> PathExplanation:
    """Build a PathExplanation with step-by-step detail."""
    concept_data = ctx.concept_views_batch(list(path.nodes()))
    details = []
    for step in path.steps:
        pred = ctx.predicate(step.predicate_id)
        subj = concept_data.get(step.subject_id, {})
        obj = concept_data.get(step.object_id, {})
        details.append({
            "subject_id": step.subject_id,
            "subject_name": subj.get("concept_name", f"Unknown ({step.subject_id})"),
            "subject_vocab": subj.get("vocabulary_id", "?"),
            "predicate_id": step.predicate_id,
            "predicate_name": pred.relationship_name if pred else step.predicate_id,
            "predicate_kind": ctx.predicate_kind(step.predicate_id).value,
            "object_id": step.object_id,
            "object_name": obj.get("concept_name", f"Unknown ({step.object_id})"),
            "object_vocab": obj.get("vocabulary_id", "?"),
        })
    return PathExplanation(path=path, profile=profile, step_details=tuple(details))


def find_ranked_paths(
    ctx: GraphContext,
    source: int,
    target: int,
    *,
    predicate_kinds: set[PredicateKind] | None = None,
    max_depth: int = 6,
    max_paths: int = 10,
) -> list[PathExplanation]:
    """Find shortest paths between two concepts using bidirectional BFS.

    Returns paths ranked by quality (PathProfile.rank_tuple), each with
    step-by-step explanations including concept names and relationship types.

    Parameters
    ----------
    ctx : GraphContext
        Graph context with DuckDB connection and caches.
    source : int
        Starting concept_id.
    target : int
        Target concept_id.
    predicate_kinds : set of PredicateKind, optional
        Restrict traversal to these edge types. None = all edges.
    max_depth : int
        Maximum path length in hops (default 6).
    max_paths : int
        Maximum number of paths to return (default 10).
    """
    if source == target:
        empty_path = GraphPath(steps=())
        profile = PathProfile(0, 0, 0, 0, 0, 0, 0)
        return [PathExplanation(path=empty_path, profile=profile, step_details=())]

    # Resolve relationship_ids for the requested predicate kinds
    rel_ids = ctx.relationship_ids_for_kinds(predicate_kinds) if predicate_kinds else None

    q_fwd: deque[int] = deque([source])
    q_bwd: deque[int] = deque([target])

    depth_fwd: dict[int, int] = {source: 0}
    depth_bwd: dict[int, int] = {target: 0}

    parents_fwd: dict[int, list[tuple[int, str]]] = defaultdict(list)
    parents_bwd: dict[int, list[tuple[int, str]]] = defaultdict(list)

    best_total: int | None = None
    meeting_nodes: set[int] = set()

    while q_fwd or q_bwd:
        # Expand the smaller frontier first (bidirectional optimization)
        expand_forward = len(q_fwd) <= len(q_bwd) if q_bwd else True
        if not q_fwd:
            expand_forward = False
        if not q_bwd:
            expand_forward = True

        if expand_forward:
            # Drain current level of forward frontier for batch fetching
            frontier = []
            while q_fwd:
                node = q_fwd.popleft()
                d = depth_fwd[node]
                if d < max_depth:
                    frontier.append((node, d))
                if q_fwd and depth_fwd.get(q_fwd[0], 0) != d:
                    break  # next level — stop draining

            if not frontier:
                if not q_bwd:
                    break
                continue

            frontier_ids = [n for n, _ in frontier]
            edges_by_src = ctx.outgoing_edges_batch(frontier_ids, rel_ids)

            for cur, d in frontier:
                for e in edges_by_src.get(cur, []):
                    nxt = e.object_id
                    nd = d + 1

                    if nxt not in depth_fwd:
                        depth_fwd[nxt] = nd
                        q_fwd.append(nxt)

                    if depth_fwd[nxt] == nd:
                        parents_fwd[nxt].append((cur, e.predicate_id))

                    if nxt in depth_bwd:
                        total = nd + depth_bwd[nxt]
                        if best_total is None or total < best_total:
                            best_total = total
                            meeting_nodes = {nxt}
                        elif total == best_total:
                            meeting_nodes.add(nxt)
        else:
            frontier = []
            while q_bwd:
                node = q_bwd.popleft()
                d = depth_bwd[node]
                if d < max_depth:
                    frontier.append((node, d))
                if q_bwd and depth_bwd.get(q_bwd[0], 0) != d:
                    break

            if not frontier:
                if not q_fwd:
                    break
                continue

            frontier_ids = [n for n, _ in frontier]
            edges_by_tgt = ctx.incoming_edges_batch(frontier_ids, rel_ids)

            for cur, d in frontier:
                for e in edges_by_tgt.get(cur, []):
                    prev = e.subject_id
                    nd = d + 1

                    if prev not in depth_bwd:
                        depth_bwd[prev] = nd
                        q_bwd.append(prev)

                    if depth_bwd[prev] == nd:
                        parents_bwd[prev].append((cur, e.predicate_id))

                    if prev in depth_fwd:
                        total = depth_fwd[prev] + nd
                        if best_total is None or total < best_total:
                            best_total = total
                            meeting_nodes = {prev}
                        elif total == best_total:
                            meeting_nodes.add(prev)

        # Pruning: stop when remaining frontier can't beat the best path
        if best_total is not None:
            min_fwd = min((depth_fwd[n] for n in q_fwd), default=max_depth + 1)
            min_bwd = min((depth_bwd[n] for n in q_bwd), default=max_depth + 1)
            if min_fwd + min_bwd >= best_total:
                break

    if not meeting_nodes:
        return []

    # Reconstruct and rank
    raw_paths: list[GraphPath] = []
    for meet in meeting_nodes:
        raw_paths.extend(
            _reconstruct_paths(source, target, meet, parents_fwd, parents_bwd, max_paths)
        )
        if len(raw_paths) >= max_paths:
            break

    raw_paths = raw_paths[:max_paths]

    # Score and sort
    explanations = []
    for path in raw_paths:
        profile = _compute_profile(ctx, path)
        explanation = _build_explanation(ctx, path, profile)
        explanations.append(explanation)

    explanations.sort(key=lambda e: e.profile.rank_tuple())
    return explanations
