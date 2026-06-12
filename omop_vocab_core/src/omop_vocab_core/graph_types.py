"""Data types for OMOP vocabulary graph traversal and pathfinding."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PredicateKind(Enum):
    """Semantic classification of OMOP relationship types.

    Derived at runtime from the RELATIONSHIP table's is_hierarchical,
    defines_ancestry, and relationship_name fields.
    """

    ONTOLOGICAL = "ontological"
    MAPPING = "mapping"
    VERSIONING = "versioning"
    ATTRIBUTE = "attribute"
    METADATA = "metadata"


@dataclass(frozen=True)
class PredicateInfo:
    """Metadata for a single OMOP relationship type."""

    relationship_id: str
    relationship_name: str
    reverse_relationship_id: str | None
    is_hierarchical: bool
    defines_ancestry: bool
    kind: PredicateKind


@dataclass(frozen=True)
class EdgeView:
    """A single directed edge in the concept relationship graph."""

    subject_id: int
    predicate_id: str
    object_id: int


@dataclass(frozen=True)
class PathStep:
    """One hop in a path: subject --[predicate]--> object."""

    subject_id: int
    predicate_id: str
    object_id: int


@dataclass(frozen=True)
class GraphPath:
    """An ordered sequence of steps connecting two concepts."""

    steps: tuple[PathStep, ...]

    def nodes(self) -> tuple[int, ...]:
        """Return all concept_ids along the path in order."""
        if not self.steps:
            return ()
        ids = [self.steps[0].subject_id]
        for step in self.steps:
            ids.append(step.object_id)
        return tuple(ids)

    @property
    def hops(self) -> int:
        return len(self.steps)

    @property
    def source(self) -> int:
        return self.steps[0].subject_id

    @property
    def target(self) -> int:
        return self.steps[-1].object_id


@dataclass(frozen=True)
class PathProfile:
    """Quality metrics for a graph path, used for ranking.

    Lower rank tuple = better path.
    """

    hops: int
    invalid_concepts: int
    non_standard_concepts: int
    vocab_switches: int
    ontological_edges: int
    mapping_edges: int
    metadata_edges: int

    def rank_tuple(self) -> tuple[int, int, int, int, int, int]:
        """Ranking key: lower is better.

        Priority: invalid > non_standard > metadata > mapping > vocab_switches > hops
        Ontological edges are good, so they don't appear as a penalty.
        """
        return (
            self.invalid_concepts,
            self.non_standard_concepts,
            self.metadata_edges,
            self.mapping_edges,
            self.vocab_switches,
            self.hops,
        )


@dataclass(frozen=True)
class PathExplanation:
    """A ranked path with its profile and step-by-step detail."""

    path: GraphPath
    profile: PathProfile
    step_details: tuple[dict, ...]  # each: {subject, predicate, object, predicate_kind}


@dataclass(frozen=True)
class SubgraphResult:
    """A neighborhood subgraph returned by BFS exploration."""

    nodes: list[dict]  # concept metadata dicts
    edges: list[dict]  # {source_id, source_name, relationship, target_id, target_name}
    seed_ids: list[int]
    depth: int
    truncated: bool  # True if max_nodes limit was hit
