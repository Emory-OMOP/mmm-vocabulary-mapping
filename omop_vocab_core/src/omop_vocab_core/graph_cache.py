"""GraphContext: in-process cache over a DuckDB connection for graph traversal."""

from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from typing import Iterator

from .db import get_connection
from .graph_queries import (
    fetch_all_predicates,
    fetch_concept_batch,
    fetch_incoming_edges,
    fetch_outgoing_edges,
)
from .graph_types import EdgeView, PredicateInfo, PredicateKind

# Maximum edges returned per concept during BFS expansion.
MAX_EDGES_PER_NODE = 200


def _classify_predicate(
    relationship_id: str,
    relationship_name: str,
    is_hierarchical: bool,
    defines_ancestry: bool,
    reverse_name: str | None,
) -> PredicateKind:
    """Classify a relationship into a PredicateKind using RELATIONSHIP table fields.

    Logic ported from omop-graph's Predicate.classify_predicate().
    """
    if defines_ancestry:
        return PredicateKind.ONTOLOGICAL

    name_lower = relationship_name.lower()

    if any(tok in name_lower for tok in ("maps to", "mapped from", "equivalent")):
        return PredicateKind.MAPPING

    if "replaced" in name_lower or "replaces" in name_lower:
        return PredicateKind.VERSIONING

    if name_lower.startswith("has "):
        return PredicateKind.ATTRIBUTE

    # Check if the reverse relationship is an "has ..." attribute —
    # if so, this side is metadata (e.g., "Ingredient of" is the reverse of "Has ingredient").
    if reverse_name and reverse_name.lower().startswith("has "):
        return PredicateKind.ATTRIBUTE

    return PredicateKind.METADATA


class GraphContext:
    """Holds a DuckDB connection and dict caches for one graph operation.

    Caches are scoped to the lifetime of this object (one tool call).
    """

    def __init__(self, conn):
        self._conn = conn
        self._concept_cache: dict[int, dict] = {}
        self._out_edges: dict[int, list[EdgeView]] = {}
        self._in_edges: dict[int, list[EdgeView]] = {}
        self._predicates: dict[str, PredicateInfo] = {}
        self._relationship_ids_by_kind: dict[PredicateKind, list[str]] = defaultdict(list)
        self._load_predicates()

    def _load_predicates(self) -> None:
        """Bulk-load all relationship metadata and classify them."""
        rows = fetch_all_predicates(self._conn)
        # First pass: build name lookup for reverse-relationship classification
        name_by_id = {r["relationship_id"]: r["relationship_name"] for r in rows}

        for row in rows:
            rel_id = row["relationship_id"]
            reverse_id = row["reverse_relationship_id"]
            reverse_name = name_by_id.get(reverse_id) if reverse_id else None
            is_hier = str(row["is_hierarchical"]) == "1"
            def_anc = str(row["defines_ancestry"]) == "1"

            kind = _classify_predicate(
                rel_id, row["relationship_name"], is_hier, def_anc, reverse_name
            )
            info = PredicateInfo(
                relationship_id=rel_id,
                relationship_name=row["relationship_name"],
                reverse_relationship_id=reverse_id,
                is_hierarchical=is_hier,
                defines_ancestry=def_anc,
                kind=kind,
            )
            self._predicates[rel_id] = info
            self._relationship_ids_by_kind[kind].append(rel_id)

    def predicate(self, relationship_id: str) -> PredicateInfo | None:
        return self._predicates.get(relationship_id)

    def predicate_kind(self, relationship_id: str) -> PredicateKind:
        info = self._predicates.get(relationship_id)
        return info.kind if info else PredicateKind.METADATA

    def relationship_ids_for_kinds(
        self, kinds: set[PredicateKind]
    ) -> list[str] | None:
        """Return relationship_ids matching the given kinds, or None for all."""
        if not kinds:
            return None
        ids: list[str] = []
        for k in kinds:
            ids.extend(self._relationship_ids_by_kind.get(k, []))
        return ids if ids else None

    def concept_view(self, concept_id: int) -> dict | None:
        """Get concept metadata, using cache."""
        if concept_id not in self._concept_cache:
            results = fetch_concept_batch(self._conn, [concept_id])
            if results:
                self._concept_cache[concept_id] = results[0]
            else:
                return None
        return self._concept_cache.get(concept_id)

    def concept_views_batch(self, concept_ids: list[int]) -> dict[int, dict]:
        """Batch-fetch concept metadata, populating the cache."""
        missing = [cid for cid in concept_ids if cid not in self._concept_cache]
        if missing:
            for row in fetch_concept_batch(self._conn, missing):
                self._concept_cache[row["concept_id"]] = row
        return {
            cid: self._concept_cache[cid]
            for cid in concept_ids
            if cid in self._concept_cache
        }

    def _load_outgoing(
        self, concept_ids: list[int], relationship_ids: list[str] | None
    ) -> None:
        """Fetch and cache outgoing edges for concepts not yet cached."""
        to_fetch = [cid for cid in concept_ids if cid not in self._out_edges]
        if not to_fetch:
            return
        raw = fetch_outgoing_edges(self._conn, to_fetch, relationship_ids)
        # Group by source
        by_source: dict[int, list[EdgeView]] = defaultdict(list)
        for src, rel, tgt in raw:
            by_source[src].append(EdgeView(subject_id=src, predicate_id=rel, object_id=tgt))
        for cid in to_fetch:
            self._out_edges[cid] = by_source.get(cid, [])[:MAX_EDGES_PER_NODE]

    def _load_incoming(
        self, concept_ids: list[int], relationship_ids: list[str] | None
    ) -> None:
        """Fetch and cache incoming edges for concepts not yet cached."""
        to_fetch = [cid for cid in concept_ids if cid not in self._in_edges]
        if not to_fetch:
            return
        raw = fetch_incoming_edges(self._conn, to_fetch, relationship_ids)
        by_target: dict[int, list[EdgeView]] = defaultdict(list)
        for src, rel, tgt in raw:
            by_target[tgt].append(EdgeView(subject_id=src, predicate_id=rel, object_id=tgt))
        for cid in to_fetch:
            self._in_edges[cid] = by_target.get(cid, [])[:MAX_EDGES_PER_NODE]

    def outgoing_edges(
        self, concept_id: int, relationship_ids: list[str] | None = None
    ) -> list[EdgeView]:
        self._load_outgoing([concept_id], relationship_ids)
        return self._out_edges.get(concept_id, [])

    def incoming_edges(
        self, concept_id: int, relationship_ids: list[str] | None = None
    ) -> list[EdgeView]:
        self._load_incoming([concept_id], relationship_ids)
        return self._in_edges.get(concept_id, [])

    def outgoing_edges_batch(
        self, concept_ids: list[int], relationship_ids: list[str] | None = None
    ) -> dict[int, list[EdgeView]]:
        """Batch-fetch outgoing edges for a frontier of concept_ids."""
        self._load_outgoing(concept_ids, relationship_ids)
        return {cid: self._out_edges.get(cid, []) for cid in concept_ids}

    def incoming_edges_batch(
        self, concept_ids: list[int], relationship_ids: list[str] | None = None
    ) -> dict[int, list[EdgeView]]:
        """Batch-fetch incoming edges for a frontier of concept_ids."""
        self._load_incoming(concept_ids, relationship_ids)
        return {cid: self._in_edges.get(cid, []) for cid in concept_ids}

    def is_ancestor(self, ancestor_id: int, descendant_id: int) -> int | None:
        """Check ancestry via CONCEPT_ANCESTOR. Returns separation or None."""
        from .graph_queries import fetch_ancestor_check
        return fetch_ancestor_check(self._conn, ancestor_id, descendant_id)


@contextmanager
def graph_context() -> Iterator[GraphContext]:
    """Context manager that yields a GraphContext backed by a DuckDB connection."""
    with get_connection() as conn:
        yield GraphContext(conn)
